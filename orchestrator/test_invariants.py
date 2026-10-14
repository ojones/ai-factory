"""One test per design invariant in docs/invariants.md. Run: python3 -m unittest discover orchestrator

The meta test at the bottom keeps the table and these tests in step: every INV-NN row has exactly one
`test_invNN_...` here and every test here has a row.
"""
import json
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
import retrospective as pm  # noqa: E402

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

    def test_inv04_the_verdict_comes_from_the_findings_and_their_structure(self):
        backed = {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "x", "evidence": "e",
                  "file": "backend/src/a.ts", "line": "3", "requirement": "", "suggested_fix": "", "repro": ""}
        clean, blocking, _ = b.derive_review({"verdict": "clean", "findings": [backed]})
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)
        self.assertTrue(b.derive_review({"verdict": "changes_requested", "findings": []})[0])
        # a blocking label does not block unless its fields back it: an opinion, or a category that cannot block, is minor
        self.assertTrue(b.derive_review({"findings": [dict(backed, evidence_kind="opinion")]})[0])
        self.assertTrue(b.derive_review({"findings": [dict(backed, category="style")]})[0])
        with self.assertRaises(ValueError):  # no structure at all: the reviewer is asked again, a label is not trusted
            b.derive_review({"findings": [{"severity": "blocking", "summary": "x"}]})

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
            bud.mint("m/x")
        body = http.call_args[0][3]
        self.assertEqual(body["models"], ["m/x"])
        self.assertAlmostEqual(body["spending_limit"], 1.5)

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

    def test_inv14_the_retrospective_agent_cannot_change_workflows_or_protected_files(self):
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

    def test_inv17_finalize_and_the_retrospective_always_run(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/build-run.yml").read_text())
        steps = next(iter(wf["jobs"].values()))["steps"]
        for needle in ("build_run.py finalize", "retrospective.py"):
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

    def test_inv20_the_retrospective_agent_never_gets_the_parent_key(self):
        cfg = {"limits": {"retrospective_cost_cap_usd": 0.5, "jwt_ttl_seconds": 60}, "roles": {"retrospective": {"model": "m/x"}}}
        with mock.patch.object(pm.b, "http", return_value=(200, {"token": "scoped"})):
            self.assertEqual(pm.mint_agent_key(cfg, "parent-key"), "scoped")
        with mock.patch.object(pm.b, "http", return_value=(500, {})):
            self.assertIsNone(pm.mint_agent_key(cfg, "parent-key"))
        source = (ROOT / "orchestrator/retrospective.py").read_text()
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

    def test_inv25_nothing_is_reverted_in_git_and_only_a_regression_rolls_the_deploy_back_through_ci(self):
        import inspect
        d = {"commits": ["h"], "base_sha": "b", "head_sha": "h", "release": None}
        self.assertTrue(b.rollback_decision(dict(d, outcome="regression"))[0])
        for outcome in ("released", "nothing_to_release", "planned", "watchdog_disabled", "round_limit", "needs_human", "stuck",
                        "budget_exhausted", "time_limit", "crash", "provider_blocked"):
            self.assertFalse(b.rollback_decision(dict(d, outcome=outcome))[0], outcome)
        # the Orchestrator has no way to revert: no function, and the rollback runs the app's own workflow and touches no git
        self.assertFalse(hasattr(b, "revert_main_to_base"))
        src = inspect.getsource(b.rollback_deploy)
        self.assertIn("ROLLBACK_WORKFLOW", src)
        self.assertNotIn('"git"', src)
        wf = yaml.safe_load((ROOT / "templates/starter/.github/workflows/rollback-fly.yml").read_text())
        self.assertIn("workflow_dispatch", wf[True])
        self.assertIn("rollback-fly.yml", b.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR[-1])  # template sync gives existing apps the workflow
        import audit
        self.assertTrue(audit.audit_report(dict(d, outcome="regression", stages=[], blocking=[], rollback={"status": "failed", "reason": "x"})))
        self.assertTrue(audit.audit_report(dict(d, outcome="round_limit", stages=[], blocking=[], revert={"status": "reverted"})))

    def test_inv26_a_bad_ending_is_handled_on_the_stories_own_issue_or_as_one_fix_request(self):
        import fixrequest as fr, retrospective as pm
        for outcome in ("round_limit", "needs_human", "stuck", "budget_exhausted", "time_limit", "crash", "watchdog_disabled"):
            self.assertTrue(pm.wants_fix_request({"outcome": outcome}, {}), outcome)
        for outcome in ("released", "nothing_to_release", "planned"):
            self.assertFalse(pm.wants_fix_request({"outcome": outcome}, {}), outcome)
        self.assertEqual((fr.route("plan_gap"), fr.route("spec_ambiguity"), fr.route("infra"), fr.route(None)), ("factory", "app", "info", "info"))
        self.assertEqual(fr.route(fr.inferred_category(None, "watchdog_disabled")), "app")  # a release the watchdog switched off is the story's to fix
        self.assertEqual(fr.fingerprint("a", "1", "factory"), fr.fingerprint("a", "1", "factory"))
        self.assertNotEqual(fr.fingerprint("a", "1", "factory"), fr.fingerprint("a", "2", "factory"))
        state = {"attempt": 1, "last_run": "r1"}
        self.assertEqual(fr.retry_decision(state, {"run_url": "r1"}, {})[0], True)  # the same failure twice is one attempt

    def test_inv27_self_correction_runs_on_the_same_issue_and_flag_and_is_bounded(self):
        import fixrequest as fr
        lim = {"fix_request_max_attempts": 2}
        self.assertEqual([fr.should_autostart("app", n, lim) for n in (1, 2, 3, 4)], [True, True, False, False])
        self.assertFalse(fr.should_autostart("factory", 1, lim))  # a Factory fix is a PR a person merges
        self.assertEqual(PROFILES["limits"]["fix_request_max_attempts"], 2)
        self.assertTrue(PROFILES["limits"]["fix_request_autostart"])
        hidden = fr.with_retry_state({"attempt": 2, "flags": ["f"], "history": ["--x--"], "last_run": "r"})
        self.assertEqual(fr.retry_state(["no state here", "note " + hidden]), {"attempt": 2, "flags": ["f"], "history": ["--x--"], "last_run": "r"})
        self.assertEqual(fr.retry_decision({"attempt": 2, "last_run": "r"}, {"run_url": "r2"}, lim), (False, 3, False))  # out of tries: stays for a person
        import update_intake as u
        calls = []

        def fake(args, token, check=False):
            calls.append((args, token))
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout='{"body": "x", "url": "https://github.com/o/f/issues/7", "comments": []}')
            return mock.Mock(stdout="[]")

        facts = {"app": "demo", "outcome": "round_limit", "message": "m", "run_url": "u", "issue_number": "7", "flags": ["demo-flag"]}
        with mock.patch.object(fr, "gh", fake), mock.patch.object(u, "gh", fake):
            out = fr.file_fix_request("o/f", "actions", "the-pat", facts, {"category": "spec_ambiguity"}, None, lim)
        self.assertTrue(out["started"])
        self.assertFalse([a for a, _ in calls if a[:2] == ["issue", "create"]])  # the same issue, never a new one
        self.assertEqual([t for a, t in calls if a[:2] == ["issue", "edit"] and u.GO in a], ["the-pat"])  # the PAT, so the label event starts the workflow

    def test_inv28_a_check_that_admits_it_was_not_observed_does_not_pass(self):
        real = "Unable to directly observe logs in production, but feature flag mechanism is working correctly"
        self.assertEqual(b.check_state({"status": "passed", "evidence": real}), "not_run")
        self.assertFalse(b.derive_test({"results": [{"flag": "a", "check": "x", "status": "passed", "evidence": real}]}, ["a"])[0])
        self.assertEqual(b.check_state({"status": "passed", "evidence": "Status: 200"}), "passed")
        self.assertEqual(b.check_state({"status": "passed", "evidence": "Cannot see logs, but npm run test:file shows 1 passed"}), "passed")

    def test_inv29_a_provider_with_no_balance_stops_the_run_and_retries_nothing(self):
        import fixrequest as fr, retrospective as pm
        event = '{"code": "LLMBadRequestError", "detail": "OpenAIException - You need positive balance to do inference", "kind": "ConversationErrorEvent"}'
        self.assertTrue(b.provider_blocked_text(event))
        self.assertFalse(b.provider_blocked_text("the spec mentions a positive balance"))
        with mock.patch.object(b, "http", return_value=(402, {})):
            with self.assertRaises(b.ProviderBlocked):
                b.provider_check("https://x/v1", "k", "m")
            with self.assertRaises(b.ProviderBlocked):
                b.Budget("admin", 1.0, 60).mint("m")
        self.assertFalse(pm.wants_fix_request({"outcome": "provider_blocked"}, {}))  # no self-starting retry
        self.assertFalse(pm.records_stuck_issue("provider_blocked"))
        self.assertNotIn("provider_blocked", b.OK_OUTCOMES)

    def test_inv30_the_api_check_helpers_observation_outranks_the_testers_judgement(self):
        import api_check as ac
        api = {"create": {"id": "create", "ok": False, "problems": ["status: expected 201, got 200"], "observed": {"status": 200}}}
        passed = {"flag": "f", "check": "create", "status": "passed", "passed": True, "evidence": "ok", "api": ["create"]}
        out = b.reconcile_api_checks({"results": [passed]}, api)
        self.assertEqual(b.check_state(out["results"][0]), "failed")
        self.assertEqual(b.check_state(b.reconcile_api_checks({"results": [passed]}, {})["results"][0]), "not_run")
        left_out = b.reconcile_api_checks({"results": [{"flag": "f", "check": "x", "status": "passed", "passed": True, "evidence": "e"}]}, api)
        self.assertEqual(b.check_state(left_out["results"][-1]), "failed")
        self.assertIsNotNone(ac.validate([{"id": "a", "request": {"path": "https://other.example/"}, "expect": {"status": 200}}])[1])

    def test_inv31_production_feedback_is_rate_limited_and_owner_only(self):
        import production_feedback as pf
        cfg = {"min_occurrences": 3, "max_per_app_per_day": 2}
        groups = {"a" * 8: {"count": 9, "message": "m", "frame": ""}, "b" * 8: {"count": 8, "message": "n", "frame": ""},
                  "c" * 8: {"count": 1, "message": "o", "frame": ""}}
        self.assertEqual(pf.decide(groups, {}, 0, 0, cfg)[0], ["a" * 8])  # one at a time, below-threshold ignored
        self.assertEqual(pf.decide(groups, {}, 1, 0, cfg)[0], [])         # one already open for the app
        self.assertEqual(pf.decide(groups, {}, 0, 2, cfg)[0], [])         # the daily limit
        self.assertEqual(pf.decide(groups, {"a" * 8: 5}, 1, 0, cfg), ([], ["a" * 8]))  # a repeat comments
        import inspect
        self.assertIn('!= owner', inspect.getsource(pf.scan_defect_labels))  # a defect label by anyone but the owner is skipped

    def test_inv32_a_silent_agent_is_killed_long_before_the_overall_timeout(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.jsonl"
        rc = b.run_watched([sys.executable, "-c", "import time; time.sleep(60)"], None, os.environ.copy(), out, 30, 1, poll=0.2)
        self.assertEqual(rc, "stall")
        self.assertGreater(PROFILES["limits"]["agent_stall_minutes"], 0)
        self.assertLess(PROFILES["limits"]["agent_stall_minutes"], PROFILES["limits"]["agent_timeout_minutes"])

    def test_inv33_template_sync_is_an_intake_for_agent_changeable_files_once_per_target(self):
        import template_sync as ts
        applicable, protected, _ = ts.split_changes([("M", "package.json"), ("M", "fly.toml"), ("M", ".github/x.yml")])
        self.assertEqual([p for _, p in applicable], ["package.json"])
        self.assertEqual(len(protected), 2)
        t, base = "a" * 40, "b" * 40
        self.assertTrue(ts.should_sync(applicable, t, base, [], [], "a"))
        self.assertFalse(ts.should_sync([], t, base, [], [], "a"))
        self.assertFalse(ts.should_sync(applicable, t, t, [], [], "a"))
        self.assertFalse(ts.should_sync(applicable, t, base, [f"a: template sync [sync {t[:7]}]"], [], "a"))
        self.assertFalse(ts.should_sync(applicable, t, base, [], [{"number": 1}], "a"))
        triggers = yaml.safe_load((ROOT / ".github/workflows/template-sync.yml").read_text())[True]
        self.assertNotIn("push", triggers)  # a merge to main never starts a Build Run: the nightly pass or a manual run does
        self.assertIn("schedule", triggers)

    def test_inv34_agents_run_as_a_separate_account_and_the_run_proves_it(self):
        cmd = b.agent_command(["openhands"], {"PATH": "/p", "LLM_API_KEY": "secret-jwt"}, "agent")
        self.assertEqual(cmd[:4], ["sudo", "-n", "-u", "agent"])
        self.assertNotIn("secret-jwt", " ".join(cmd))
        self.assertIn("GIT_CONFIG_VALUE_0", b.git_auth_env("h"))
        self.assertTrue(b.isolation_problems({"whoami": "runner", "environ": "SELF-CHECK-SECRET", "workspace": "x", "env_names": "FACTORY_PAT", "sudo": "yes"}))
        self.assertEqual(PROFILES["limits"]["agent_isolation"], "user")

    def test_inv35_updates_reach_apps_only_as_gated_intakes(self):
        import maintenance as mt
        npm = {"number": 1, "title": "Bump a from 1 to 2", "url": "u", "headRefName": "dependabot/npm_and_yarn/a-2", "labels": []}
        acts = {"number": 2, "title": "Bump actions/checkout", "url": "u", "headRefName": "dependabot/github_actions/x", "labels": []}
        applicable, reported = mt.split_prs([npm, acts])
        self.assertEqual((applicable, reported), ([npm], [acts]))
        key = mt.update_key(applicable)
        self.assertTrue(mt.should_file(applicable, key, [], []))
        self.assertFalse(mt.should_file(applicable, key, [f"a: dependency updates [maint {key}]"], []))
        self.assertFalse(mt.should_file(applicable, key, [], [{"number": 9}]))
        self.assertEqual(set(b.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR), {".github/dependabot.yml", ".github/workflows/test-gate.yml", ".github/workflows/rollback-fly.yml"})

    def test_inv36_the_browser_helpers_observation_outranks_the_testers_judgement(self):
        import ui_check as uc
        ui = {"s": {"id": "s", "ok": False, "problems": ["role='button': expected it to be visible, but it is not"], "observed": {}}}
        passed = {"flag": "f", "check": "c", "status": "passed", "passed": True, "evidence": "e", "ui": ["s"]}
        self.assertEqual(b.check_state(b.reconcile_ui_checks({"results": [passed]}, ui)["results"][0]), "failed")
        self.assertEqual(b.check_state(b.reconcile_ui_checks({"results": [passed]}, {})["results"][0]), "not_run")
        self.assertEqual(b.check_state(b.reconcile_ui_checks({"results": [{**passed, "ui": []}]}, ui)["results"][-1]), "failed")
        self.assertIsNotNone(uc.validate([{"id": "a", "start": "https://other.example/", "expect": {"visible": [{"label": "x"}]}}])[1])
        self.assertNotIn("TKN-secret", uc.scrub("/?preview=TKN-secret and TKN-secret", "TKN-secret"))
        self.assertRegex((ROOT / "agents/playwright-version.txt").read_text().strip(), r"^\d+\.\d+\.\d+$")
        self.assertIn("playwright-version.txt", (ROOT / ".github/workflows/build-run.yml").read_text())

    def test_inv37_flags_are_retired_inside_an_update_run_only_when_proven(self):
        import flag_retirement as fr
        released = lambda slug, run, state="released": {"key": f"a.feature.{slug}", "date": "2026-10-01", "run_url": f"https://x/runs/{run}", "state": state}
        flags = [released("old", 1), released("older", 2), released("new", 9), released("dead", 3, "switched off by the watchdog")]
        got = fr.piggyback_slugs(flags, {"old", "older", "new", "dead"}, "2026-10-12", 1, 5)
        self.assertEqual(got, ["old", "older"])  # oldest first; the newest release keeps its flag; a watchdog-off flag is dead, not retired
        self.assertEqual(fr.piggyback_slugs(flags, {"old", "older", "new"}, "2026-10-12", 1, 1), ["old"])
        self.assertEqual(fr.piggyback_slugs(flags, {"old", "older", "new"}, "2026-10-01", 1, 5), [])  # released today: not a day yet
        self.assertEqual(b.retire_slugs(fr.retirement_block(["old", "older"])), ["old", "older"])
        self.assertIsNotNone(b.retirement_problem("old", b.code_references(['h:src/a.ts:3:  isFeatureEnabled(res, "old")'])))
        self.assertEqual(b.removed_flag_slugs('[{"slug":"old"}]', "[]"), ["old"])
        self.assertGreaterEqual(PROFILES["limits"]["flag_retirement"]["piggyback_max"], 1)

    def test_inv38_a_flag_and_its_story_point_at_each_other(self):
        self.assertEqual(b.title_with_flags("app: a page", ["x"]), "app: a page [flag: x]")
        self.assertEqual(b.flag_label("x"), "flag:x")
        self.assertIn("issues/9", b.flag_description("https://github.com/o/r/issues/9", "t"))
        self.assertEqual(b.flag_tags(9, "app"), ["intake-9", "app-app"])
        import appstate
        self.assertIn("issues/9", appstate.story_link({"issue": 9, "run_url": "https://github.com/o/r/actions/runs/1"}))
        run = object.__new__(b.BuildRun)
        run.update_intake, run.issue_title = False, "app"  # a first build's title is never touched
        calls = []
        run.gh = lambda *a, **k: calls.append(a)
        run.link_flags_to_issue(["x"])
        self.assertEqual(calls, [])

    def test_inv39_a_story_and_its_flag_live_and_die_together(self):
        import fixrequest as fr
        import planner as pl
        plan = {"requirements": [{"id": "REQ-1", "text": "t"}], "assumptions": [], "open_questions": [],
                "change_sets": [{"id": "CS-1", "title": "T", "requirements": ["REQ-1"], "depends_on": [], "criteria": ["AC-1: x"], "verification": ["v"],
                                 "flag": "other", "internal_only": False, "out_of_scope": []}]}
        self.assertTrue(pl.validate_plan(plan, "update", 8, ["story-flag"])[0])  # a retry may not invent another flag
        self.assertIn("story-flag", fr.retry_note(["story-flag"], 2))
        self.assertEqual(fr.retry_state([fr.with_retry_state({"flags": ["story-flag"]})])["flags"], ["story-flag"])
        for fn in ("release", "disable_flags"):
            self.assertTrue(hasattr(b.BuildRun, fn))

    def test_inv40_an_impossible_request_is_refused_before_anything_is_built(self):
        import triage as tr
        import retrospective as pm2
        self.assertEqual(tr.find_secrets("key sk-" + "x1y2z3w4v5u6t7s8r9q0p1o2"), ["an API key (sk- style)"])
        self.assertEqual(tr.find_secrets("add a password field"), [])
        self.assertTrue(tr.feasibility({"feasibility": {"status": "blocked", "category": "payments", "reasons": ["card"]}})[0])
        self.assertFalse(tr.feasibility({"feasibility": {"status": "ok"}})[0])
        self.assertFalse(pm2.wants_fix_request({"outcome": "refused"}, {}))
        self.assertNotIn("refused", b.OK_OUTCOMES)
        self.assertTrue(issubclass(b.Refused, Exception))

    def test_inv41_a_model_swap_is_decided_by_a_measured_pass_and_survivable_at_run_time(self):
        import benchmark as bm
        base = {"tasks": 7, "passed": 6, "cost_usd": 2.0, "minutes": 100, "rounds_mean": 1.5,
                "by_task": {"refuse-secret": {"passed": True, "tags": ["refusal"], "outcome": "refused"}}}
        better = {"tasks": 7, "passed": 6, "cost_usd": 1.0, "minutes": 60, "rounds_mean": 1.4, "by_task": base["by_task"]}
        self.assertTrue(bm.compare(better, base)["accept"] and bm.compare(better, base)["improvement"])
        careless = {**better, "by_task": {"refuse-secret": {"passed": False, "tags": ["refusal"], "outcome": "released"}}}
        self.assertFalse(bm.compare(careless, base)["accept"])  # cheaper, but it stopped refusing
        self.assertFalse(bm.compare({**better, "cost_usd": 3.0}, base)["accept"])
        text = (ROOT / "agents/profiles.yml").read_text()
        doc = yaml.safe_load(bm.candidate_profile(text, {"coder": "x/y"}))
        self.assertEqual((doc["roles"]["coder"]["model"], doc["limits"]["flag_retirement"]["piggyback_max"]), ("x/y", 0))
        run = object.__new__(b.BuildRun)
        run.update_intake = False
        run.cfg = {"provider": {"base_url": "u"}, "roles": {"coder": {"model": "gone", "fallback_model": "ok"}}}
        run.state = b.State(Path("/tmp/inv41-state.json"), "a", "1", "u")
        run.state.save = lambda: None
        with mock.patch.object(b, "http", lambda m, u, t=None, body=None, timeout=60: (404, {}) if body["model"] == "gone" else (200, {})), \
                mock.patch.dict(os.environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertEqual(run.cfg["roles"]["coder"]["model"], "ok")

    def test_inv42_only_reviewed_code_is_pushed_and_the_reviewer_runs_before_the_push(self):
        import inspect
        self.assertNotIn('"push"', inspect.getsource(b.BuildRun.coder))  # the coder only commits
        run_src = inspect.getsource(b.BuildRun.run)
        self.assertLess(run_src.index("review_before_push"), run_src.index("self.push(head)"))
        self.assertLess(run_src.index("self.push(head)"), run_src.index("test_deployed"))
        self.assertIn("PipelineFix", run_src)  # a fix CI needed is reviewed again before it is pushed
        # and the run's rounds, exercised end to end with the stages stubbed (test_build_run.RoundLoop)
        from test_build_run import RoundLoop
        t = RoundLoop()
        run = t.make([t.BLOCKED, t.CLEAN], [t.PASSED])
        t.go(run)
        self.assertNotIn("push c1", run.calls)
        self.assertLess(run.calls.index("review c2"), run.calls.index("push c2"))

    def test_inv43_a_dark_feature_is_removed_only_after_the_retries_and_a_persons_approval(self):
        import flag_retirement as fr
        ready = ["update-intake", "app:notes", "flag:pin", "dark-broken", "needs-human"]
        self.assertEqual(fr.dark_removal_target(ready), ("notes", "pin", None))
        for missing in ("dark-broken", "needs-human"):  # while retries remain, or when nothing is dark-broken, the label does nothing
            self.assertIsNotNone(fr.dark_removal_target([l for l in ready if l != missing])[2])
        wf = yaml.safe_load((ROOT / ".github/workflows/approve-retire.yml").read_text())
        self.assertEqual(wf[True]["issues"]["types"], ["labeled"])
        self.assertIn("approve-retire", wf["jobs"]["approve"]["if"])
        d = {"flags": ["pin"], "commits": ["h"], "outcome": "round_limit"}
        self.assertTrue(b.is_dark_broken(d))  # a run that stops marks the feature; nothing deletes it
        self.assertTrue(b.is_dark_broken(dict(d, outcome="regression")))  # rolled back, but its code stays in main behind the flag
        self.assertFalse(b.is_dark_broken(dict(d, outcome="released")))

    def test_inv44_the_tester_says_what_a_failure_means_and_only_what_a_helper_saw_is_a_regression(self):
        new_check = {"flag": "f", "check": "c", "status": "failed", "scope": "new", "api": ["a"]}
        old_check = {"flag": "", "check": "c", "status": "failed", "scope": "existing", "api": ["a"]}
        self.assertEqual((b.test_impact([]), b.test_impact([new_check]), b.test_impact([old_check])), ("ok", "dark_only", "regression"))
        self.assertEqual(b.test_impact([dict(old_check, api=[], ui=[])]), "dark_only")  # the model's word alone is not a regression
        self.assertEqual(b.test_impact([dict(old_check, status="blocked")]), "dark_only")
        doc = {"improvements": [{"target": "factory", "summary": "x", "evidence": ""}, {"target": "other", "summary": "y"}]}
        self.assertEqual([i["target"] for i in b.improvements_from(doc, "tester")], ["factory"])  # the Agents suggest; they file nothing
        import retrospective as pm
        self.assertTrue(hasattr(pm, "note_bugs_on_story") and not hasattr(pm, "record_bugs"))  # bugs go on the story, never a new issue
        self.assertGreaterEqual(len(pm.content_words("Coder prompt does not say to trim the input") & pm.content_words("The coder prompt never says to trim input")), 4)

    def test_inv45_the_retrospective_agent_is_isolated_like_the_build_run_agents(self):
        import inspect
        import retrospective as pm
        src = inspect.getsource(pm.run_agent)
        self.assertIn("run_isolation_probes", src)
        self.assertIn("user=user", src)
        self.assertIn("apply_changes", src)
        self.assertNotIn("subprocess.run", src)
        self.assertNotIn('"git"', inspect.getsource(pm.run_tests) + inspect.getsource(pm.tree_changes) + inspect.getsource(pm.apply_changes))
        self.assertIn("run_tests(", inspect.getsource(pm.open_pr))  # the tests of the proposal never run in the Orchestrator's own environment
        self.assertNotIn("unittest", inspect.getsource(pm.open_pr).replace("run_tests", ""))
        for name in ("build-run.yml", "factory-run.yml"):
            text = (ROOT / ".github/workflows" / name).read_text()
            self.assertIn("useradd -m -s /bin/bash agent", text, name)
            self.assertIn("AGENT_USER=agent", text, name)
        self.assertEqual(pm.tree_changes.__module__, "retrospective")

    def test_inv46_what_blocks_or_retries_is_decided_from_structure_not_labels(self):
        from test_build_run import RoundLoop, finding
        self.assertFalse(b.derive_review({"findings": [finding()]})[0])
        for weak in (finding(evidence_kind="opinion"), finding(category="style"), finding(file="", line="")):
            self.assertTrue(b.derive_review({"findings": [weak]})[0])
        found = b.flag_findings(lambda *a: json.dumps([{"slug": "s", "description": "none"}]) if a[0] == "show" else "", "head", ["s"])
        self.assertEqual({f["severity"] for f in found}, {"minor"})
        failed = {"flag": "f", "check": "c", "status": "failed"}
        self.assertEqual(b.failed_checks([failed, {"status": "blocked"}, {"status": "not_run"}]), [failed])
        t = RoundLoop()
        run = t.make([t.CLEAN], [t.UNVERIFIED_BLOCKED, t.UNVERIFIED_BLOCKED])
        t.go(run)
        self.assertEqual(run.state.d["outcome"], "needs_human")
        self.assertEqual(run.calls.count("coder2"), 0)  # no coder round for checks nobody could run


class Registry(unittest.TestCase):
    def test_the_table_and_the_tests_list_the_same_invariants(self):
        table = set(re.findall(r"^\| INV-(\d\d) \|", (ROOT / "docs/invariants.md").read_text(), re.M))
        tests = set(re.findall(r"def test_inv(\d\d)_", Path(__file__).read_text()))
        self.assertEqual(table - tests, set(), "invariants with no test")
        self.assertEqual(tests - table, set(), "tests for invariants that are not in docs/invariants.md")
        self.assertTrue(table)


if __name__ == "__main__":
    unittest.main()
