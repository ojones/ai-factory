import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from shared.fake_issues import FakeIssues

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flag_lifecycle import flag_slug, retirement_selection  # noqa: E402
from flag_lifecycle.fake_growthbook import FakeGrowthBook  # noqa: E402
from shared import child_tickets, config, http_client, provider, run_stops  # noqa: E402

from build_run import prepare_run, review_code, track_progress  # noqa: E402
from build_run import run as run_module
from build_run.run import BuildRun  # noqa: E402


def retirement_entry(slug, run, date="2026-10-10", state="released"):
    return {"key": f"app.feature.{slug}", "date": date, "run_url": f"https://github.com/o/r/actions/runs/{run}", "state": state}


class InstallDependencies(unittest.TestCase):
    def run_in(self, tmp, with_lock):
        run = object.__new__(BuildRun)
        run.app_dir = Path(tmp)
        if with_lock:
            (Path(tmp) / "package-lock.json").write_text("{}")
        return run

    def test_no_lockfile_means_no_install(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(prepare_run, "sh") as sh:
            self.run_in(tmp, False).install_dependencies()
            sh.assert_not_called()

    def test_install_runs_without_the_runners_secrets_and_a_failure_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(prepare_run, "sh") as sh, \
                mock.patch.dict(os.environ, {"FLY_API_TOKEN": "secret", "PATH": "/bin"}):
            sh.return_value.returncode = 1
            self.run_in(tmp, True).install_dependencies()
            env = sh.call_args.kwargs["env"]
            self.assertNotIn("FLY_API_TOKEN", env)
            self.assertEqual(sh.call_args.args[0][:2], ["npm", "ci"])


class ModelFallback(unittest.TestCase):
    def run_for(self, answers, roles=None):
        run = object.__new__(BuildRun)
        run.cfg = {"provider": {"base_url": "https://llm"}, "roles": roles or {
            "coder": {"model": "a/coder", "fallback_model": "z/fallback"}, "tester": {"model": "t/tester"}, "reviewer": {"model": "r/rev"}, "planner": {"model": "p/plan"}}}
        run.state = track_progress.State(Path("/tmp/x-state.json"), "app", "1", "u")
        run.state.save = lambda: None
        asked = []

        def fake_http(method, url, token=None, body=None, timeout=60):
            asked.append(body["model"])
            return answers.get(body["model"], (200, {}))
        return run, asked, fake_http

    def test_a_missing_model_is_replaced_by_its_fallback_for_this_run_and_the_swap_is_recorded(self):
        run, asked, fake = self.run_for({"a/coder": (404, {"error": {"message": "Model not found"}})})
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertEqual(run.cfg["roles"]["coder"]["model"], "z/fallback")
        self.assertEqual(run.state.d["fallbacks"]["coder"], {"from": "a/coder", "to": "z/fallback"})
        self.assertEqual(run.cfg["roles"]["tester"]["model"], "t/tester", msg="a role whose model is served is left alone")

    def test_a_missing_model_with_no_fallback_stops_the_run_with_the_reason(self):
        run, _, fake = self.run_for({"r/rev": (400, {"error": {"message": "The model `r/rev` does not exist"}})})
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            with self.assertRaises(run_stops.NeedsHuman) as ctx:
                run.check_models()
        self.assertIn("r/rev", str(ctx.exception))
        self.assertIn("no `fallback_model`", str(ctx.exception))

    def test_a_missing_fallback_is_also_a_stop_and_each_model_is_asked_once(self):
        run, asked, fake = self.run_for({"a/coder": (404, {}), "z/fallback": (404, {})})
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            with self.assertRaises(run_stops.NeedsHuman):
                run.check_models()
        self.assertEqual(len(asked), len(set(asked)))

    def test_all_models_answering_changes_nothing_and_a_zero_balance_is_still_provider_blocked(self):
        run, _, fake = self.run_for({})
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertNotIn("fallbacks", run.state.d)
        run, _, fake = self.run_for({"a/coder": (402, {})})
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            with self.assertRaises(run_stops.ProviderBlocked):
                run.check_models()

    def test_the_planner_is_not_a_build_runs_model_the_planning_process_checks_its_own(self):
        run, asked, fake = self.run_for({})
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertNotIn("p/plan", asked)

    def test_the_status_of_a_model_is_read_from_the_answer(self):
        for answer, expected in (((200, {}), "ok"), ((404, "x"), "missing"), ((400, {"error": "model foo not found"}), "missing"),
                                 ((500, "boom"), "unknown"), ((429, "slow"), "unknown")):
            with mock.patch.object(http_client, "request", lambda *a, answer=answer, **k: answer):
                self.assertEqual(provider.model_status("https://llm", "k", "m"), expected, answer)


class ChoosingFlagsToRetire(unittest.TestCase):

    def run_for(self, flags, *, fix=None, task="Add a button", manifest="a,b,c,d", boom=False):
        run = object.__new__(BuildRun)
        run.fix_for, run.task = (fix or {}).get("origin"), task
        run.app, run.app_repo, run.pat, run.lim = "app", "o/app", "pat", {"flag_retirement": {"min_age_days": 1, "piggyback_max": 5}}
        run.git = lambda *a, check=True: type("R", (), {"stdout": json.dumps([{"slug": s} for s in manifest.split(",")])})()
        patched = mock.patch.object(retirement_selection, "app_flags", side_effect=RuntimeError("down") if boom else None, return_value=(flags, set(manifest.split(","))))
        with patched, mock.patch.object(time, "strftime", return_value="2026-10-12"):
            return run.choose_flags_to_retire()

    flags = [retirement_entry("a", 100), retirement_entry("b", 200), retirement_entry("c", 300), retirement_entry("d", 400)]

    def test_an_update_retires_the_whole_backlog_but_the_newest_release(self):
        self.assertEqual(self.run_for(self.flags), ["a", "b", "c"])

    def test_a_fix_child_retires_nothing(self):
        self.assertEqual(self.run_for(self.flags, fix={"origin": 1, "attempt": 1}), [])

    def test_a_slug_gone_from_the_manifest_is_dropped_and_a_failed_lookup_does_not_stop_the_run(self):
        self.assertEqual(self.run_for(self.flags, manifest="b,c,d"), ["b", "c"])
        self.assertEqual(self.run_for(self.flags, boom=True), [])

    def test_flags_the_owner_names_in_the_task_are_retired_too(self):
        self.assertEqual(self.run_for(self.flags, task="Do it\nretire-flag: d\n"), ["d", "a", "b", "c"])


class NamingTheFlag(unittest.TestCase):
    TASK = "Change set CS-1: T\n\nPut the whole change behind one feature flag with the slug `" + flag_slug.SLOT + "`."

    def run_for(self, tmp, task=None, flags_json=None):
        run = object.__new__(BuildRun)
        run.task, run.issue, run.factory_repo, run.app = task or self.TASK, "12", "o/f", "app"
        run.issue_url, run.issue_title = "https://github.com/o/f/issues/12", "app: add a page"
        run.gb, run.app_dir, run.story_flags = FakeGrowthBook(), Path(tmp), ()
        run.share_with_agent = lambda path: None
        run.state = track_progress.State(Path(tmp) / "state.json", "app", "12", "u")
        run.git_calls = []
        run.git = lambda *a, **k: run.git_calls.append(a)
        if flags_json is not None:
            (Path(tmp) / "flags.json").write_text(flags_json)
        return run

    def test_the_flag_is_named_after_the_issue_created_off_and_recorded_before_the_coder_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.run_for(tmp)
            run.name_the_flag()
            self.assertIn("slug `issue-12`", run.task)
            self.assertNotIn(flag_slug.SLOT, run.task)
            self.assertEqual((run.state.d["flags"], run.story_flags, run.state.d["created_flag"]), (["issue-12"], ["issue-12"], "issue-12"))
            self.assertFalse(run.gb.production_enabled("app.feature.issue-12"))
            manifest = json.loads((Path(tmp) / "flags.json").read_text())
            self.assertTrue(manifest[0]["description"].startswith("o/f#12: "))
            self.assertEqual(run.git_calls[0], ("add", "--", "flags.json"))
            self.assertIn("commit", run.git_calls[1])

    def test_the_spec_the_reviewer_and_tester_check_against_names_it_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.run_for(tmp)
            run.spec = run.task
            run.name_the_flag()
            self.assertIn("issue-12", run.spec)

    def test_an_issue_that_runs_again_keeps_the_flag_it_had_and_creates_and_commits_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.run_for(tmp)
            run.gb.features = dict(getattr(run.gb, "features", {}))
            run.name_the_flag()
            first_manifest = (Path(tmp) / "flags.json").read_text()
            again = self.run_for(tmp, flags_json=first_manifest)
            again.gb = run.gb
            again.name_the_flag()
            self.assertIn("slug `issue-12`", again.task)
            self.assertNotIn("created_flag", again.state.d, msg="an existing feature is never touched")
            self.assertEqual(again.git_calls, [], msg="nothing new to record")
            self.assertEqual((Path(tmp) / "flags.json").read_text(), first_manifest)
            self.assertFalse(again.gb.production_enabled("app.feature.issue-12"))

    def test_a_task_with_no_placeholder_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.run_for(tmp, task="Fix a typo. It needs no flag.")
            run.name_the_flag()
            self.assertEqual((run.task, run.gb.calls, run.git_calls, run.state.d["flags"] if "flags" in run.state.d else None), ("Fix a typo. It needs no flag.", [], [], None))


class SuppressionsAndLintConfig(unittest.TestCase):
    DIFF = ("diff --git a/backend/src/a.ts b/backend/src/a.ts\n--- a/backend/src/a.ts\n+++ b/backend/src/a.ts\n@@ -3,0 +4,3 @@\n"
            "+const ok = 1;\n+// eslint-disable-next-line @typescript-eslint/no-explicit-any\n+const x: any = 2;\n"
            "diff --git a/frontend/src/b.tsx b/frontend/src/b.tsx\n--- a/frontend/src/b.tsx\n+++ b/frontend/src/b.tsx\n@@ -10 +10 @@\n"
            "-old\n+// @ts-ignore\n")

    def test_an_added_suppression_is_named_with_its_place_and_is_always_minor(self):
        found = review_code.suppression_findings(lambda *a: self.DIFF, "base", "head")
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f["severity"], f["source"], f["file"], f["line"]), ("minor", "orchestrator", "backend/src/a.ts", "5"))
        self.assertIn("2 lint or type-check suppression(s)", f["summary"])
        self.assertIn("frontend/src/b.tsx:10", f["evidence"])

    def test_no_suppression_means_no_finding(self):
        self.assertEqual(review_code.suppression_findings(lambda *a: "+++ b/a.ts\n@@ -1 +1 @@\n+const x = 1;\n", "base", "head"), [])
        self.assertEqual(review_code.suppression_findings(lambda *a: "", "base", "head"), [])

    def run_with_template(self, files, labels=("template-sync",)):
        tmp = Path(tempfile.mkdtemp())
        starter = tmp / "factory" / "templates" / "starter"
        for rel, text in files.items():
            (starter / rel).parent.mkdir(parents=True, exist_ok=True)
            (starter / rel).write_text(text)
        app = tmp / "app"
        origin = tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(app)], check=True, capture_output=True)
        (app / "eslint.config.mjs").write_text("// old\n")
        (app / "a.txt").write_text("a\n")
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=app, check=True, capture_output=True, text=True).stdout.strip()
        git("checkout", "-q", "-B", "main")
        git("add", "-A")
        git("commit", "-q", "-m", "seed")
        git("push", "-q", "origin", "main")
        run = object.__new__(BuildRun)
        run.app_dir, run.agent_user, run.auth_header = app, None, "x"
        return run, git, origin, tmp / "factory"

    def test_the_lint_config_is_staged_after_the_base_and_pushed_only_with_the_coders_work(self):
        run, git, origin, factory = self.run_with_template({"eslint.config.mjs": "// new rules\n", ".github/workflows/test-gate.yml": "name: gate\n"})
        pushes = []
        real_sh = prepare_run.sh

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            if cmd[:2] == ["git", "push"]:
                pushes.append(cmd)
                return real_sh(["git", "push", "-q", "origin", "HEAD:main"], cwd=cwd, check=True)
            return real_sh(cmd, cwd=cwd, env=env, check=check, timeout=timeout)
        with mock.patch.object(config, "FACTORY_DIR", factory), mock.patch.object(prepare_run, "sh", fake_sh), mock.patch.object(run_module, "sh", fake_sh):
            run.apply_template_files({"template-sync"})
            base = run.head()
            run.stage_template_config({"template-sync"})
        self.assertEqual(len(pushes), 1, msg="only the workflow went out at once")
        self.assertEqual(git("show", "origin/main:.github/workflows/test-gate.yml"), "name: gate")
        self.assertEqual(git("show", "origin/main:eslint.config.mjs"), "// old", msg="the config alone never reaches main")
        self.assertEqual((run.app_dir / "eslint.config.mjs").read_text(), "// new rules\n")
        self.assertEqual(git("rev-parse", "HEAD~1"), base)
        self.assertEqual(git("diff", "--name-only", base, "HEAD"), "eslint.config.mjs")

    def test_without_the_template_sync_label_nothing_is_copied(self):
        run, git, _, factory = self.run_with_template({"eslint.config.mjs": "// new\n"})
        with mock.patch.object(config, "FACTORY_DIR", factory):
            run.apply_template_files({"update-app-intake"})
            run.stage_template_config({"update-app-intake"})
        self.assertEqual((run.app_dir / "eslint.config.mjs").read_text(), "// old\n")


class LocatingThePlan(unittest.TestCase):
    MARKER = {"parent": 7, "cs": "CS-1", "kind": "update", "flag": True, "size": "S"}

    def run_for(self, marker, parent_state="open", has_parent=True):
        gh = FakeIssues()
        gh.add(7, state=parent_state)
        child = gh.add(12)
        if has_parent:
            gh.subs[7] = [child]
        run = object.__new__(BuildRun)
        run.plan_meta, run.issue, run.factory_repo, run.factory_token = marker, str(child), "o/f", "tok"
        run.state = track_progress.State("/tmp/unused-state.json", "app", str(child), "u")
        run.gh = lambda args, token=None, check=True: gh(args, token)
        return run

    def test_a_child_of_an_open_plan_reads_only_the_parents_number(self):
        run = self.run_for(self.MARKER)
        run.locate_plan()
        self.assertEqual((run.parent, run.state.d["parent"]), (7, 7))

    def test_a_child_with_a_marker_but_no_parent_is_refused(self):
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            self.run_for(self.MARKER, has_parent=False).locate_plan()
        self.assertIn("not planned yet", str(cm.exception))
        self.assertIn("not a sub-issue of any plan", str(cm.exception))

    def test_a_child_whose_plan_has_since_closed_is_refused(self):
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            self.run_for(self.MARKER, parent_state="closed").locate_plan()
        self.assertIn("is closed", str(cm.exception))

    def test_a_marker_naming_another_plan_is_refused(self):
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            self.run_for(dict(self.MARKER, parent=9)).locate_plan()
        self.assertIn("names #9 but it is a sub-issue of #7", str(cm.exception))

    def test_an_unplanned_update_intake_is_refused(self):
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            self.run_for({}, has_parent=False).locate_plan()
        self.assertIn("no plan marker", str(cm.exception))

    def test_a_lookup_that_fails_is_loud(self):
        run = self.run_for(self.MARKER)
        run.gh = lambda args, token=None, check=True: mock.Mock(returncode=1, stdout="", stderr="HTTP 500")
        with self.assertRaises(child_tickets.ChildTicketError):
            run.locate_plan()

    def test_a_staging_child_is_never_built(self):
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            self.run_for(dict(self.MARKER, kind="staging")).locate_plan()
        self.assertIn("staging child", str(cm.exception))

    def test_a_fix_child_names_its_own_flag_like_any_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = NamingTheFlag()
            run = t.run_for(tmp)
            run.plan_meta = dict(self.MARKER, fix_for=4, fix_attempt=1)
            run.name_the_flag()
            self.assertIn("slug `issue-12`", run.task)
            self.assertEqual(run.state.d["flags"], ["issue-12"])
            self.assertTrue(run.gb.production_enabled("app.feature.issue-12") is False)


if __name__ == "__main__":
    unittest.main()
