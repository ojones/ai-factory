import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flag_lifecycle import flag_manifest, flag_slug, retirement_selection  # noqa: E402
from flag_lifecycle.fake_growthbook import FakeGrowthBook  # noqa: E402
from shared import config, http_client, provider, run_stops  # noqa: E402

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
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(prepare_run, "sh") as sh:
            self.run_in(tmp, False).install_dependencies()
            sh.assert_not_called()

    def test_install_runs_without_the_runners_secrets_and_a_failure_is_not_fatal(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(prepare_run, "sh") as sh, \
                mock.patch.dict(os.environ, {"FLY_API_TOKEN": "secret", "PATH": "/bin"}):
            sh.return_value.returncode = 1
            self.run_in(tmp, True).install_dependencies()
            env = sh.call_args.kwargs["env"]
            self.assertNotIn("FLY_API_TOKEN", env)
            self.assertEqual(sh.call_args.args[0][:2], ["npm", "ci"])


class ModelFallback(unittest.TestCase):
    def run_for(self, answers, roles=None, update=True):
        # A BuildRun whose provider answers per model id (status, body).
        run = object.__new__(BuildRun)
        run.update_intake = update
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
        self.assertEqual(run.cfg["roles"]["tester"]["model"], "t/tester")  # a role whose model is served is left alone

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

    def test_a_first_build_does_not_check_the_planner(self):
        run, asked, fake = self.run_for({}, update=False)
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertNotIn("p/plan", asked)
        run, asked, fake = self.run_for({})  # an update does ask for the planner's model
        with mock.patch.object(http_client, "request", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertIn("p/plan", asked)

    def test_the_status_of_a_model_is_read_from_the_answer(self):
        for answer, expected in (((200, {}), "ok"), ((404, "x"), "missing"), ((400, {"error": "model foo not found"}), "missing"),
                                 ((500, "boom"), "unknown"), ((429, "slow"), "unknown")):
            with mock.patch.object(http_client, "request", lambda *a, answer=answer, **k: answer):
                self.assertEqual(provider.model_status("https://llm", "k", "m"), expected, answer)


class ChoosingFlagsToRetire(unittest.TestCase):
    # BuildRun.choose_flags_to_retire with the State issue and manifest mocked.

    def run_for(self, flags, *, update=True, fix=None, kind="update", task="Add a button", manifest="a,b,c,d", boom=False):
        run = object.__new__(BuildRun)
        run.update_intake, run.fix_meta, run.build_kind, run.task = update, fix or {}, kind, task
        run.app, run.app_repo, run.pat, run.lim = "app", "o/app", "pat", {"flag_retirement": {"min_age_days": 1, "piggyback_max": 5}}
        run.git = lambda *a, check=True: type("R", (), {"stdout": json.dumps([{"slug": s} for s in manifest.split(",")])})()
        patched = mock.patch.object(retirement_selection, "app_flags", side_effect=RuntimeError("down") if boom else None, return_value=(flags, set(manifest.split(","))))
        with patched, mock.patch.object(time, "strftime", return_value="2026-10-12"):
            return run.choose_flags_to_retire()

    flags = [retirement_entry("a", 100), retirement_entry("b", 200), retirement_entry("c", 300), retirement_entry("d", 400)]

    def test_an_update_retires_the_whole_backlog_but_the_newest_release(self):
        self.assertEqual(self.run_for(self.flags), ["a", "b", "c"])

    def test_a_first_build_and_an_automatic_retry_retire_nothing(self):
        self.assertEqual(self.run_for(self.flags, kind="first build"), [])
        self.assertEqual(self.run_for(self.flags, fix={"origin": 1, "attempt": 1}), [])
        self.assertEqual(self.run_for(self.flags, update=False), [])

    def test_a_slug_gone_from_the_manifest_is_dropped_and_a_failed_lookup_does_not_stop_the_run(self):
        self.assertEqual(self.run_for(self.flags, manifest="b,c,d"), ["b", "c"])
        self.assertEqual(self.run_for(self.flags, boom=True), [])

    def test_flags_the_owner_names_in_the_task_are_retired_too(self):
        self.assertEqual(self.run_for(self.flags, task="Do it\nretire-flag: d\n", kind="update"), ["d", "a", "b", "c"])


class NamingTheFlag(unittest.TestCase):
    TASK = "Change set CS-1: T\n\nPut the whole change behind one feature flag with the slug `" + flag_slug.SLOT + "`."

    def run_for(self, tmp, task=None, reuse=(), flags_json=None):
        run = object.__new__(BuildRun)
        run.task, run.reuse_flags, run.issue, run.factory_repo, run.app = task or self.TASK, list(reuse), "12", "o/f", "app"
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

    def test_a_retried_story_keeps_the_flag_it_had_and_nothing_new_is_created_or_committed(self):
        on = {"environments": {"production": {"enabled": False, "rules": []}}}
        with tempfile.TemporaryDirectory() as tmp:
            run = self.run_for(tmp, reuse=["todo-ui"], flags_json='[{"slug": "todo-ui", "description": "o/f#12: x"}]')
            run.gb = FakeGrowthBook({"app.feature.todo-ui": on})
            run.name_the_flag()
            self.assertIn("slug `todo-ui`", run.task)
            self.assertEqual((run.git_calls, "created_flag" in run.state.d), ([], False))
            self.assertEqual(run.story_flags, ["todo-ui"])
            self.assertEqual([c[0] for c in run.gb.calls], ["GET"])

    def test_a_task_with_no_placeholder_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.run_for(tmp, task="Fix a typo. It needs no flag.")
            run.name_the_flag()
            self.assertEqual((run.task, run.gb.calls, run.git_calls, run.state.d["flags"] if "flags" in run.state.d else None), ("Fix a typo. It needs no flag.", [], [], None))


class RetryState(unittest.TestCase):
    def test_setup_reads_the_retry_state_from_the_issue_comments(self):
        from try_fix import fix_request as fr
        hidden = fr.with_retry_state({"attempt": 1, "flags": ["todo-ui"], "history": ["h"], "guidance": "Fix the regression.", "cap": 1.5})
        retry = fr.retry_state([c for c in ["note", hidden]])
        self.assertEqual(retry["flags"], ["todo-ui"])
        self.assertTrue(all(flag_manifest.SLUG_RE.fullmatch(f) for f in retry["flags"]))


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
        # A real app checkout with a base commit, and a Starter Template folder holding `files`.
        import tempfile
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
        from unittest import mock
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
        self.assertEqual(len(pushes), 1)  # only the workflow went out at once
        self.assertEqual(git("show", "origin/main:.github/workflows/test-gate.yml"), "name: gate")
        self.assertEqual(git("show", "origin/main:eslint.config.mjs"), "// old")  # the config alone never reaches main
        self.assertEqual((run.app_dir / "eslint.config.mjs").read_text(), "// new rules\n")
        self.assertEqual(git("rev-parse", "HEAD~1"), base)  # the staged config commit sits after the run's base, so a rollback target was deployed
        self.assertEqual(git("diff", "--name-only", base, "HEAD"), "eslint.config.mjs")

    def test_without_the_template_sync_label_nothing_is_copied(self):
        run, git, _, factory = self.run_with_template({"eslint.config.mjs": "// new\n"})
        from unittest import mock
        with mock.patch.object(config, "FACTORY_DIR", factory):
            run.apply_template_files({"update-app-intake"})
            run.stage_template_config({"update-app-intake"})
        self.assertEqual((run.app_dir / "eslint.config.mjs").read_text(), "// old\n")


if __name__ == "__main__":
    unittest.main()
