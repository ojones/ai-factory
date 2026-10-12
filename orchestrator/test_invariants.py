"""One test per design invariant in docs/invariants.md. Run: python3 -m unittest discover orchestrator

The meta test at the bottom keeps the table and these tests in step: every INV-NN row has exactly one
`test_invNN_...` here and every test here has a row.
"""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import postmortem as pm  # noqa: E402

ROOT = b.FACTORY_DIR
PROFILES = yaml.safe_load((ROOT / "agents/profiles.yml").read_text())
ARCH = (ROOT / "ARCHITECTURE.md").read_text()
STARTER = ROOT / "templates/starter"


class Invariants(unittest.TestCase):
    def test_inv01_an_agent_gets_a_whitelisted_environment(self):
        secrets = {"FACTORY_PAT": "pat-secret", "FLY_API_TOKEN": "fly-secret", "GROWTHBOOK_ADMIN_PAT": "gb-secret",
                   "DEEPINFRA_API_KEY": "parent-secret", "PREVIEW_MASTER_SECRET": "master-secret", "FACTORY_GH_TOKEN": "gh-secret"}
        run = object.__new__(b.BuildRun)
        run.cfg = {"roles": {"coder": {"model": "m/x"}}, "provider": {"base_url": "https://llm"}}
        with mock.patch.dict(os.environ, secrets):
            env = run.agent_env("coder", "scoped-jwt")
        self.assertEqual(env["LLM_API_KEY"], "scoped-jwt")
        self.assertFalse(set(secrets.values()) & set(env.values()))
        self.assertFalse(set(secrets) & set(env))
        allowed = {"PATH", "HOME", "LANG", "TMPDIR", "CI", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "RUNTIME"}
        self.assertLessEqual(set(env), allowed)

    def test_inv02_a_protected_file_in_a_coder_commit_is_rejected(self):
        files = [".github/workflows/deploy-fly.yml", "fly.toml", "fly/provision.sh", "backend/src/feature-flags.ts", "INTAKE.md"]
        self.assertEqual(b.protected_violations(files), files)
        self.assertEqual(b.protected_violations(["backend/src/routes/notes.ts", "flags.json"]), [])

    def test_inv03_release_needs_all_four_conditions_for_the_same_sha(self):
        self.assertTrue(b.release_gate(True, True, True, True, "a", "a"))
        for i in range(4):
            args = [True] * 4
            args[i] = False
            self.assertFalse(b.release_gate(*args, "a", "a"))
        self.assertFalse(b.release_gate(True, True, True, True, "a", "b"))

    def test_inv04_the_verdict_comes_from_the_findings(self):
        clean, blocking, _ = b.derive_review({"verdict": "clean", "findings": [{"severity": "blocking", "summary": "x"}]})
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)
        self.assertTrue(b.derive_review({"verdict": "changes_requested", "findings": []})[0])

    def test_inv05_only_a_passed_check_passes(self):
        for state in ("failed", "blocked", "not_run"):
            self.assertFalse(b.derive_test({"results": [{"flag": "a", "check": "x", "status": state}]}, ["a"])[0], state)
        self.assertTrue(b.derive_test({"results": [{"flag": "a", "check": "x", "status": "passed"}]}, ["a"])[0])

    def test_inv06_release_never_touches_a_flag_that_already_exists(self):
        calls = []

        def gb(method, path, body=None):
            calls.append((method, path))
            if path.startswith("/projects"):
                return 200, {"projects": [{"id": "p"}]}
            if method == "GET":
                return (200, {}) if path.endswith(".old") else (404, {})
            return 200, {}

        run = object.__new__(b.BuildRun)
        run.app, run.app_repo, run.run_id, run.run_url = "demo", "o/demo", "1", "u"
        run.gb, run.gh = gb, mock.Mock()
        run.state = b.State("/tmp/unused-state.json", "demo", "1", "u")
        run.state.save = lambda: None
        run.release(["old", "new"], "sha")
        posts = [path for method, path in calls if method == "POST"]
        self.assertEqual(posts, ["/features"])
        self.assertEqual(run.state.d["release"], {"released": ["demo.feature.new"], "kept": ["demo.feature.old"]})

    def test_inv07_the_watchdog_switches_off_only_what_its_run_released(self):
        run = object.__new__(b.BuildRun)
        run.lim = {"watchdog_minutes": 0.05, "watchdog_interval_seconds": 0, "watchdog_max_failures": 1, "watchdog_max_errors": 5}
        run.app, run.deadline = "demo", float("inf")
        run.state = b.State("/tmp/unused-state.json", "demo", "1", "u")
        run.state.save = lambda: None
        run.state.d["release"] = {"released": ["demo.feature.new"], "kept": ["demo.feature.old"]}
        run.app_error_count = lambda: 0
        run.disable_flags = mock.Mock(return_value=[])
        with mock.patch.object(b, "http", return_value=(500, {})), mock.patch.object(b.time, "sleep"):
            run.watch_release()
        run.disable_flags.assert_called_once_with(["demo.feature.new"])

    def test_inv08_the_preview_token_matches_the_staging_script(self):
        shell = subprocess.run([str(ROOT / "infra/app-staging/preview-token.sh"), "demo-app"],
                               env={**os.environ, "PREVIEW_MASTER_SECRET": "x"}, capture_output=True, text=True)
        self.assertEqual(shell.stdout.strip(), b.preview_token("x", "demo-app"))

    def test_inv09_each_credential_is_single_model_and_limited_to_what_is_left(self):
        with mock.patch.object(b, "http", return_value=(200, {"token": "jwt"})) as http:
            bud = b.Budget("admin", 2.0, 100)
            bud.tokens["earlier"] = 0.5
            bud.mint("m/x", 0.5)
        body = http.call_args[0][3]
        self.assertEqual(body["models"], ["m/x"])
        self.assertAlmostEqual(body["spending_limit"], 0.75)

    def test_inv10_a_cap_override_above_the_ceiling_or_not_above_zero_is_refused(self):
        form = "### What should be built?\n\nA thing\n\n### Cost cap override (USD)\n\n{}\n"
        for bad in ("10.01", "0", "-1"):
            with self.assertRaises(b.NeedsHuman):
                b.parse_intake(form.format(bad), PROFILES["limits"]["cost_cap_usd_default"], PROFILES["limits"]["cost_cap_usd_ceiling"])
        self.assertEqual(b.parse_intake(form.format("10"), 2.0, PROFILES["limits"]["cost_cap_usd_ceiling"])[1], 10.0)

    def test_inv11_the_review_round_limit_in_the_docs_is_the_configured_one(self):
        m = re.search(r"default \*\*(\d+)\*\*[^.]*`limits\.review_rounds`", ARCH)
        self.assertIsNotNone(m, "ARCHITECTURE.md should state the default review rounds next to `limits.review_rounds`")
        self.assertEqual(int(m.group(1)), PROFILES["limits"]["review_rounds"])

    def test_inv12_the_models_in_the_docs_are_the_configured_ones(self):
        for role in ("coder", "reviewer"):
            model = PROFILES["roles"][role]["model"]
            self.assertIn(f"`{model}`", ARCH, f"ARCHITECTURE.md does not name the {role} model {model}")

    def test_inv13_every_configured_prompt_exists_in_the_factory_repo(self):
        for role, profile in PROFILES["roles"].items():
            for key in ("prompt", "fast_prompt"):
                if key in profile:
                    self.assertTrue((ROOT / "agents" / profile[key]).is_file(), f"{role}.{key} -> {profile[key]}")
        self.assertFalse((STARTER / "agents").exists())

    def test_inv14_the_postmortem_agent_cannot_change_workflows_or_protected_files(self):
        for bad in (".github/workflows/build-run.yml", "templates/starter/.github/workflows/build.yml", "templates/starter/fly.toml",
                    "templates/starter/fly/provision.sh", "agents/../.github/x.yml", "README.md"):
            self.assertFalse(pm.allowed_path(bad), bad)
        for ok in ("agents/prompts/coder.md", "templates/starter/AGENTS.md", "orchestrator/build_run.py", "STANDARDS-CODING.md"):
            self.assertTrue(pm.allowed_path(ok), ok)

    def test_inv15_only_additive_lint_or_formatter_config_auto_merges(self):
        self.assertTrue(pm.auto_merge_eligible("4\t0\ttemplates/starter/.eslintrc.json"))
        for bad in ("4\t1\ttemplates/starter/.eslintrc.json", "4\t0\tagents/prompts/coder.md",
                    "4\t0\ttemplates/starter/package.json", ""):
            self.assertFalse(pm.auto_merge_eligible(bad), bad)

    def test_inv16_the_starter_flags_fail_closed_and_the_kill_switch_is_placed_correctly(self):
        sources = {p: p.read_text() for p in (STARTER / "backend/src").rglob("*.ts") if "__tests__" not in p.parts}
        for path, text in sources.items():
            self.assertIsNone(re.search(r"getBooleanValue\([^)]*,\s*true\s*\)", text), f"{path} reads a flag with default true")
        app = sources[STARTER / "backend/src/app.ts"]
        self.assertIn("getBooleanValue(killSwitchKey(), false)", app)
        health, kill, static = (app.index(x) for x in ("app.use(healthRouter)", "getBooleanValue(killSwitchKey()", "app.use(express.static"))
        self.assertLess(health, kill)
        self.assertLess(kill, static)

    def test_inv17_finalize_and_the_postmortem_always_run(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/build-run.yml").read_text())
        steps = next(iter(wf["jobs"].values()))["steps"]
        for needle in ("build_run.py finalize", "postmortem.py"):
            step = next(s for s in steps if needle in s.get("run", ""))
            self.assertEqual(str(step.get("if")).strip(), "always()", needle)

    def test_inv18_one_app_never_has_overlapping_or_cancelled_build_runs(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/build-run.yml").read_text())
        group = wf["concurrency"]
        self.assertIn("inputs.app_name", group["group"])
        self.assertIs(group["cancel-in-progress"], False)
        self.assertEqual(group.get("queue"), "max")  # otherwise GitHub cancels all but one pending run

    def test_inv19_a_run_that_changes_nothing_stops(self):
        entry = {"round": 1, "sha": "a", "counts": {}, "checks": {"a: x": "failed"}, "blocking": ["no flag"]}
        n = PROFILES["limits"]["stuck_rounds"]
        self.assertGreaterEqual(n, 2)
        self.assertTrue(b.stalled([dict(entry, round=i) for i in range(n)], n))
        self.assertFalse(b.stalled([dict(entry, round=i) for i in range(n - 1)], n))

    def test_inv20_the_postmortem_agent_never_gets_the_parent_key(self):
        cfg = {"limits": {"postmortem_cost_cap_usd": 0.5, "jwt_ttl_seconds": 60}, "roles": {"postmortem": {"model": "m/x"}}}
        with mock.patch.object(pm.b, "http", return_value=(200, {"token": "scoped"})):
            self.assertEqual(pm.mint_agent_key(cfg, "parent-key"), "scoped")
        with mock.patch.object(pm.b, "http", return_value=(500, {})):
            self.assertIsNone(pm.mint_agent_key(cfg, "parent-key"))
        source = (ROOT / "orchestrator/postmortem.py").read_text()
        self.assertNotIn('"LLM_API_KEY": os.environ', source)

    def test_inv21_openhands_is_pinned_everywhere_it_is_installed(self):
        version = (ROOT / "agents/openhands-version.txt").read_text().strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        installs = 0
        for wf in (ROOT / ".github/workflows").glob("*.yml"):
            for line in wf.read_text().splitlines():
                if "pip install" in line and "openhands" in line:
                    installs += 1
                    self.assertIn("openhands==$(cat ", line, f"{wf.name}: {line.strip()}")
                    self.assertIn("agents/openhands-version.txt", line, wf.name)
        self.assertGreaterEqual(installs, 4)

    def test_inv22_an_update_intake_changes_only_a_repo_this_factory_created(self):
        import update_intake as u
        self.assertTrue(u.is_factory_repo("Intake: o/ai-factory#3", "o/ai-factory"))
        for bad in ("Intake: o/other#3", "", None, "my own project"):
            self.assertFalse(u.is_factory_repo(bad, "o/ai-factory"), bad)
        calls = []

        def fake(args, token, check=False):
            calls.append(args)
            return mock.Mock(stdout='{"description": "my own project"}', returncode=0, stderr="")

        env = {"FACTORY_REPO": "o/ai-factory", "FACTORY_PAT": "p", "GH_TOKEN": "t", "ISSUE_NUMBER": "9", "RUN_URL": "u",
               "ISSUE_BODY": "### App name\n\nnotes\n\n### What should change?\n\nx\n"}
        with mock.patch.dict(os.environ, env), mock.patch.object(u, "gh", fake):
            self.assertEqual(u.start(), 1)
        self.assertFalse([c for c in calls if c[:2] == ["workflow", "run"]])

    def test_inv23_a_change_set_starts_only_after_its_dependencies_close_and_only_once(self):
        import update_intake as u
        kid = lambda n, state, labels, deps: {"number": n, "state": state, "labels": set(labels), "depends_on": deps}
        self.assertEqual(u.ready_to_start([kid(1, "OPEN", [], []), kid(2, "OPEN", [u.WAIT], [1])]), [])
        self.assertEqual(u.ready_to_start([kid(1, "CLOSED", [], []), kid(2, "OPEN", [u.WAIT], [1])]), [2])
        self.assertEqual(u.ready_to_start([kid(1, "CLOSED", [], []), kid(2, "OPEN", [u.WAIT, u.GO], [1])]), [])
        # one at a time: a second ready change set waits, and nothing starts while one is in flight
        self.assertEqual(u.ready_to_start([kid(1, "CLOSED", [], []), kid(2, "OPEN", [u.WAIT], [1]), kid(3, "OPEN", [u.WAIT], [1])]), [2])
        self.assertEqual(u.ready_to_start([kid(1, "OPEN", [u.GO], []), kid(2, "OPEN", [u.WAIT], [])]), [])

    def test_inv24_only_the_go_label_on_an_update_intake_starts_a_run_and_modules_agree_on_good_endings(self):
        import appstate, audit, dashboard
        wf = yaml.safe_load((ROOT / ".github/workflows/update-intake.yml").read_text())
        self.assertEqual(wf[True]["issues"]["types"], ["labeled"])  # YAML reads the key `on` as True
        cond = " ".join(next(iter(wf["jobs"].values()))["if"].split())
        self.assertIn("github.event.label.name == 'proceed-with-change'", cond)
        self.assertIn("contains(github.event.issue.labels.*.name, 'update-intake')", cond)
        self.assertEqual(set(b.OK_OUTCOMES), set(audit.OK_OUTCOMES) & set(appstate.OK) & set(dashboard.OK))
        self.assertIn("planned", b.OK_OUTCOMES)

    def test_inv25_a_failed_run_leaves_main_as_it_found_it(self):
        from test_revert import Repo, git
        r = Repo()
        self.assertEqual(b.revert_main_to_base(r.d, r.work)["status"], "reverted")
        self.assertEqual(git(r.origin, "diff", "--stat", r.base, "main"), "")
        self.assertEqual(git(r.origin, "rev-list", "--count", "main"), "3")  # history kept, nothing rewritten
        moved = Repo()
        moved.other_pushes("someone else\n")
        self.assertEqual(b.revert_main_to_base(moved.d, moved.work)["status"], "skipped")  # never over someone else's commit
        d = {"commits": ["h"], "base_sha": "b", "head_sha": "h", "release": None}
        for outcome in ("released", "nothing_to_release", "planned", "watchdog_disabled"):
            self.assertFalse(b.revert_decision(dict(d, outcome=outcome), "all")[0], outcome)
        self.assertTrue(b.revert_decision(dict(d, outcome="round_limit"), "all")[0])
        import audit
        self.assertTrue(audit.audit_report(dict(d, outcome="round_limit", stages=[], blocking=[], revert={"status": "failed", "reason": "x"})))

    def test_inv26_a_bad_ending_gets_one_fix_request_per_intake(self):
        import fixrequest as fr, postmortem as pm
        for outcome in ("round_limit", "needs_human", "stuck", "budget_exhausted", "time_limit", "crash", "watchdog_disabled"):
            self.assertTrue(pm.wants_fix_request({"outcome": outcome}, {}), outcome)
        for outcome in ("released", "nothing_to_release", "planned"):
            self.assertFalse(pm.wants_fix_request({"outcome": outcome}, {}), outcome)
        self.assertEqual((fr.route("plan_gap"), fr.route("spec_ambiguity"), fr.route("infra"), fr.route(None)), ("factory", "app", "info", "info"))
        self.assertEqual(fr.fingerprint("a", "1", "app"), fr.fingerprint("a", "1", "app"))
        self.assertNotEqual(fr.fingerprint("a", "1", "app"), fr.fingerprint("a", "2", "app"))

    def test_inv27_self_correction_starts_itself_but_is_bounded(self):
        import fixrequest as fr
        lim = {"fix_request_max_attempts": 2}
        self.assertEqual([fr.should_autostart("app", n, lim) for n in (1, 2, 3, 4)], [True, True, False, False])
        self.assertFalse(fr.should_autostart("factory", 1, lim))  # a Factory fix is a PR a person merges
        self.assertEqual(PROFILES["limits"]["fix_request_max_attempts"], 2)
        self.assertTrue(PROFILES["limits"]["fix_request_autostart"])
        body = fr.update_intake.with_fix_meta({"origin": 1, "attempt": 2})
        self.assertEqual(fr.attempt_info(body, "9")[:2], (1, 3))  # a failed retry files the next attempt, counting up
        import update_intake as u
        calls = []

        def fake(args, token, check=False):
            calls.append((args, token))
            if args[:2] == ["issue", "create"]:
                return mock.Mock(stdout="https://github.com/o/f/issues/80\n")
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout='{"body": "### App name\\n\\ndemo\\n\\n### What should change?\\n\\nx\\n"}')
            return mock.Mock(stdout="[]")

        facts = {"app": "demo", "outcome": "round_limit", "message": "m", "run_url": "u", "issue_number": "7"}
        with mock.patch.object(fr, "gh", fake), mock.patch.object(u, "gh", fake):
            out = fr.file_fix_request("o/f", "actions", "the-pat", facts, {"category": "spec_ambiguity"}, None, lim)
        self.assertTrue(out["started"])
        starts = [(a, t) for a, t in calls if a[:2] == ["issue", "edit"] and u.GO in a]
        self.assertEqual([t for _, t in starts], ["the-pat"])  # the PAT, so the label event starts the workflow


class Registry(unittest.TestCase):
    def test_the_table_and_the_tests_list_the_same_invariants(self):
        table = set(re.findall(r"^\| INV-(\d\d) \|", (ROOT / "docs/invariants.md").read_text(), re.M))
        tests = set(re.findall(r"def test_inv(\d\d)_", Path(__file__).read_text()))
        self.assertEqual(table - tests, set(), "invariants with no test")
        self.assertEqual(tests - table, set(), "tests for invariants that are not in docs/invariants.md")
        self.assertTrue(table)


if __name__ == "__main__":
    unittest.main()
