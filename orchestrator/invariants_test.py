import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml
from bugs import escaped_defects, flood_limits, route_bug, scan_production
from build_run import read_child, ship_code
from build_run import start_build as u
from build_run import ui_check as uc
from build_run.run_test import RoundLoop, finding
from factory_change import file_change, gate, open_pr, pause, prove_reproduction, tiers, vet_change
from flag_lifecycle import flag_slug, missing_flag, release_features
from flag_lifecycle.fake_growthbook import FakeGrowthBook
from maintenance import dependency_updates as mt
from maintenance import template_sync as ts
from monitoring import benchmark as bm
from monitoring import dashboard
from planning import file_children, fix_for, plan_run, render_child, secrets_marker, triage, validate_plan
from planning import triage as tr
from retrospective import agent_run, app_state, close_child, event_verdicts, learning_pr, lesson_records, run_audit
from shared import api_check as ac
from shared import child_tickets
from shared import child_tickets as ct
from shared.fake_issues import FakeIssues
from staging import read_staging_child, verify_infrastructure
from try_fix import collect_events, event, factory_fix_request, file_bug, render_bug, resume_after_merge, route, validate_bug, write_bug

sys.path.insert(0, str(Path(__file__).parent))
from build_run import endings, gate_release, prepare_run, review_code, suggestions, track_progress, verify_deployed_app  # noqa: E402
from build_run import run as run_module
from build_run.run import BuildRun  # noqa: E402
from flag_lifecycle import dark_feature, flag_manifest, retirement_check, retirement_selection, story_link  # noqa: E402
from request import check_target_app, intake_labels  # noqa: E402
from retrospective import story_report, tracker  # noqa: E402
from shared import (  # noqa: E402
    agent_process,
    agent_runner,
    config,
    github,
    http_client,
    outcomes,
    preview_token,
    provider,
    rollback,  # noqa: E402
    run_stops,
    spend_budget,
    starter_template,
)

ROOT = config.FACTORY_DIR
PROFILES = yaml.safe_load((ROOT / "agents/profiles.yml").read_text())
ARCH = (ROOT / "ARCHITECTURE.md").read_text()
STARTER = ROOT / "templates/starter"


class Invariants(unittest.TestCase):
    def test_inv01_an_agent_gets_a_whitelisted_environment(self):
        secrets = {"FACTORY_PAT": "pat-secret", "FLY_API_TOKEN": "fly-secret", "GROWTHBOOK_ADMIN_PAT": "gb-secret",
                   "DEEPINFRA_API_KEY": "parent-secret", "PREVIEW_MASTER_SECRET": "master-secret", "FACTORY_GH_TOKEN": "gh-secret"}
        runner = agent_runner.AgentRunner({"roles": {"coder": {"model": "m/x"}}, "provider": {"base_url": "https://llm"}}, None, "art", "work", "cwd")
        with mock.patch.dict(os.environ, secrets):
            env = runner.agent_env("coder", "scoped-jwt")
        self.assertEqual(env["LLM_API_KEY"], "scoped-jwt")
        self.assertFalse(set(secrets.values()) & set(env.values()))
        self.assertFalse(set(secrets) & set(env))
        allowed = {"PATH", "HOME", "LANG", "TMPDIR", "CI", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "RUNTIME"}
        self.assertLessEqual(set(env), allowed)

    def test_inv02_a_protected_file_in_a_coder_commit_is_rejected(self):
        files = [".github/workflows/deploy-fly.yml", "fly.toml", "fly/provision.sh", "backend/src/feature-flags.ts", "INTAKE.md",
                 "eslint.config.mjs", ".prettierrc.json", ".prettierignore"]
        self.assertEqual(starter_template.protected_violations(files), files)
        self.assertEqual(starter_template.protected_violations(["backend/src/routes/notes.ts", "flags.json"]), [])

    def test_inv03_release_needs_all_four_conditions_for_the_same_sha(self):
        self.assertTrue(gate_release.release_gate(True, True, True, True, "a", "a"))
        for i in range(4):
            args = [True] * 4
            args[i] = False
            self.assertFalse(gate_release.release_gate(*args, "a", "a"))
        self.assertFalse(gate_release.release_gate(True, True, True, True, "a", "b"))

    def test_inv04_the_verdict_comes_from_the_findings_and_their_structure(self):
        backed = {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "x", "evidence": "e",
                  "file": "backend/src/a.ts", "line": "3", "requirement": "", "suggested_fix": "", "repro": ""}
        clean, blocking, _ = review_code.derive_review({"verdict": "clean", "findings": [backed]})
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)
        self.assertTrue(review_code.derive_review({"verdict": "changes_requested", "findings": []})[0])
        self.assertTrue(review_code.derive_review({"findings": [dict(backed, evidence_kind="opinion")]})[0])
        self.assertTrue(review_code.derive_review({"findings": [dict(backed, category="style")]})[0])
        with self.assertRaises(ValueError):
            review_code.derive_review({"findings": [{"severity": "blocking", "summary": "x"}]})

    def test_inv05_only_a_passed_check_passes(self):
        for state in ("failed", "blocked", "not_run"):
            self.assertFalse(verify_deployed_app.derive_test({"results": [{"flag": "a", "check": "x", "status": state}]}, ["a"])[0], state)
        self.assertTrue(verify_deployed_app.derive_test({"results": [{"flag": "a", "check": "x", "status": "passed"}]}, ["a"])[0])

    def test_inv06_release_switches_on_only_the_storys_own_flag_and_never_creates_or_touches_another(self):
        off = lambda: {"environments": {"production": {"enabled": False, "rules": []}}}  # noqa: E731
        gb = FakeGrowthBook({"demo.feature.old": off(), "demo.feature.issue-9": off()})
        to_switch, kept, missing = release_features.check_flags(gb, "demo", ["old", "issue-9", "ghost"], ["issue-9"])
        self.assertEqual((to_switch, kept, missing), (["demo.feature.issue-9"], ["demo.feature.old"], ["ghost"]))
        release_features.switch_on(gb, to_switch)
        self.assertEqual([c for c in gb.calls if c[0] == "POST"], [("POST", "/features/demo.feature.issue-9", {"environments": {"production": {"enabled": True, "rules": []}}})])
        self.assertNotIn("demo.feature.ghost", gb.features, msg="a missing flag is reported, never created")

    def test_inv07_the_watchdog_switches_off_only_what_its_run_released(self):
        run = object.__new__(BuildRun)
        run.lim = {"watchdog_minutes": 0.05, "watchdog_interval_seconds": 0, "watchdog_max_failures": 1, "watchdog_max_errors": 5}
        run.app, run.deadline = "demo", float("inf")
        run.state = track_progress.State("/tmp/unused-state.json", "demo", "1", "u")
        run.state.save = lambda: None
        run.state.d["release"] = {"released": ["demo.feature.new"], "kept": ["demo.feature.old"]}
        run.app_error_count = lambda: 0
        run.disable_flags = mock.Mock(return_value=[])
        with mock.patch.object(http_client, "request", return_value=(500, {})), mock.patch.object(time, "sleep"):
            run.watch_release()
        run.disable_flags.assert_called_once_with(["demo.feature.new"])

    def test_inv08_the_preview_token_matches_the_staging_script(self):
        shell = subprocess.run([str(ROOT / "infra/app-staging/preview-token.sh"), "demo-app"],
                               env={**os.environ, "PREVIEW_MASTER_SECRET": "x"}, capture_output=True, text=True)
        self.assertEqual(shell.stdout.strip(), preview_token.for_app("x", "demo-app"))

    def test_inv09_each_credential_is_single_model_and_limited_to_what_is_left(self):
        with mock.patch.object(http_client, "request", return_value=(200, {"token": "jwt"})) as http:
            bud = spend_budget.Budget("admin", 2.0, 100)
            bud.tokens["earlier"] = 0.5
            bud.mint("m/x")
        body = http.call_args[0][3]
        self.assertEqual(body["models"], ["m/x"])
        self.assertAlmostEqual(body["spending_limit"], 1.5)

    def test_inv10_a_cap_override_above_the_ceiling_or_not_above_zero_is_refused(self):
        form = "### What should be built?\n\nA thing\n\n### Cost cap override (USD)\n\n{}\n"
        for bad in ("10.01", "0", "-1"):
            with self.assertRaises(run_stops.NeedsHuman):
                read_child.parse_intake(form.format(bad), PROFILES["limits"]["cost_cap_usd_default"], PROFILES["limits"]["cost_cap_usd_ceiling"])
        self.assertEqual(read_child.parse_intake(form.format("10"), 2.0, PROFILES["limits"]["cost_cap_usd_ceiling"])[1], 10.0)

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
            self.assertFalse(agent_run.allowed_path(bad), bad)
        for ok in ("agents/prompts/coder.md", "templates/starter/AGENTS.md", "orchestrator/build_run.py", "ARCHITECTURE.md"):
            self.assertTrue(agent_run.allowed_path(ok), ok)

    def test_inv15_only_additive_lint_or_formatter_config_auto_merges(self):
        self.assertTrue(learning_pr.auto_merge_eligible("4\t0\ttemplates/starter/.eslintrc.json"))
        for bad in ("4\t1\ttemplates/starter/.eslintrc.json", "4\t0\tagents/prompts/coder.md",
                    "4\t0\ttemplates/starter/package.json", ""):
            self.assertFalse(learning_pr.auto_merge_eligible(bad), bad)

    def test_inv16_the_starter_flags_fail_closed_and_there_is_no_kill_switch(self):
        sources = {p: p.read_text() for p in (STARTER / "backend/src").rglob("*.ts") if "__tests__" not in p.parts}
        for path, text in sources.items():
            self.assertIsNone(re.search(r"getBooleanValue\([^)]*,\s*true\s*\)", text), f"{path} reads a flag with default true")
        self.assertFalse([p.name for p, text in sources.items() if "kill" in text.lower()], "the Starter has no kill switch: a feature flag per change is the only switch")
        app = sources[STARTER / "backend/src/app.ts"]
        self.assertLess(app.index("app.use(healthRouter)"), app.index("app.use(express.static"), msg="health answers before anything else is mounted")

    def test_inv17_finalize_and_the_retrospective_always_run(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/build-run.yml").read_text())
        steps = next(iter(wf["jobs"].values()))["steps"]
        for needle in ("retrospective.finalize", "retrospective.run_retrospective"):
            step = next(s for s in steps if needle in s.get("run", ""))
            self.assertEqual(str(step.get("if")).strip(), "always()", needle)

    def test_inv18_one_app_never_has_overlapping_or_cancelled_build_runs(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/build-run.yml").read_text())
        group = wf["concurrency"]
        self.assertIn("inputs.app_name", group["group"])
        self.assertIs(group["cancel-in-progress"], False)
        self.assertEqual(group.get("queue"), "max", msg="otherwise GitHub cancels all but one pending run")

    def test_inv19_a_run_that_changes_nothing_stops(self):
        entry = {"round": 1, "sha": "a", "counts": {}, "checks": {"a: x": "failed"}, "blocking": ["no flag"]}
        n = PROFILES["limits"]["stuck_rounds"]
        self.assertGreaterEqual(n, 2)
        self.assertTrue(track_progress.stalled([dict(entry, round=i) for i in range(n)], n))
        self.assertFalse(track_progress.stalled([dict(entry, round=i) for i in range(n - 1)], n))

    def test_inv20_the_retrospective_agent_never_gets_the_parent_key(self):
        cfg = {"limits": {"retrospective_cost_cap_usd": 0.5, "jwt_ttl_seconds": 60}, "roles": {"retrospective": {"model": "m/x"}}}
        with mock.patch.object(http_client, "request", return_value=(200, {"token": "scoped"})):
            self.assertEqual(agent_run.mint_agent_key(cfg, "parent-key"), "scoped")
        with mock.patch.object(http_client, "request", return_value=(500, {})):
            self.assertIsNone(agent_run.mint_agent_key(cfg, "parent-key"))
        source = (ROOT / "orchestrator/retrospective/agent_run.py").read_text()
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
        self.assertTrue(check_target_app.is_factory_repo("Intake: o/ai-factory#3", "o/ai-factory"))
        for bad in ("Intake: o/other#3", "", None, "my own project"):
            self.assertFalse(check_target_app.is_factory_repo(bad, "o/ai-factory"), bad)
        calls = []

        def fake(args, token, check=False):
            calls.append(args)
            return mock.Mock(stdout='{"description": "my own project"}', returncode=0, stderr="")

        env = {"FACTORY_REPO": "o/ai-factory", "FACTORY_PAT": "p", "GH_TOKEN": "t", "ISSUE_NUMBER": "9", "RUN_URL": "u",
               "ISSUE_BODY": "### App name\n\nnotes\n\n### What should change?\n\nx\n"}
        with mock.patch.dict(os.environ, env), mock.patch.object(github, "run", fake):
            self.assertEqual(u.start(), 1)
        self.assertFalse([c for c in calls if c[:2] == ["workflow", "run"]])

    def test_inv23_a_change_set_starts_only_after_its_blockers_close_and_only_once(self):
        W, S = child_tickets.WAIT, intake_labels.START
        kid = lambda n, state, labels: {"number": n, "state": state, "labels": set(labels)}
        blockers = lambda table: lambda n: [{"number": k, "state": v} for k, v in table.get(n, {}).items()]
        self.assertEqual(close_child.ready_to_start([kid(1, "OPEN", []), kid(2, "OPEN", [W])], blockers({2: {1: "OPEN"}})), [])
        self.assertEqual(close_child.ready_to_start([kid(1, "CLOSED", []), kid(2, "OPEN", [W])], blockers({2: {1: "CLOSED"}})), [2])
        self.assertEqual(close_child.ready_to_start([kid(1, "CLOSED", []), kid(2, "OPEN", [W, S])], blockers({2: {1: "CLOSED"}})), [])
        self.assertEqual(close_child.ready_to_start([kid(1, "CLOSED", []), kid(2, "OPEN", [W]), kid(3, "OPEN", [W])], blockers({})), [2])
        self.assertEqual(close_child.ready_to_start([kid(1, "OPEN", [S]), kid(2, "OPEN", [W])], blockers({})), [])
        self.assertEqual(close_child.ready_to_start([kid(1, "OPEN", []), kid(2, "OPEN", [W])], blockers({})), [])

    def test_inv24_only_the_go_label_on_an_update_intake_starts_a_run_and_modules_agree_on_good_endings(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/update-app-intake.yml").read_text())
        self.assertEqual(wf[True]["issues"]["types"], ["labeled"], msg="YAML reads the key `on` as True")
        cond = " ".join(next(iter(wf["jobs"].values()))["if"].split())
        self.assertIn("github.event.label.name == 'proceed-with-change'", cond)
        self.assertIn("contains(github.event.issue.labels.*.name, 'update-app-intake')", cond)
        for module in (run_module, run_audit, app_state, dashboard, lesson_records):
            self.assertIs(module.outcomes, outcomes, msg="one list of good endings, defined in shared/outcomes.py, not mirrored")
        self.assertNotIn("planned", outcomes.OK, msg="planning is its own process (plan.yml); a Build Run never ends by planning")

    def test_inv25_nothing_is_reverted_in_git_and_only_a_regression_rolls_the_deploy_back_through_ci(self):
        d = {"commits": ["h"], "base_sha": "b", "head_sha": "h", "release": None}
        self.assertTrue(rollback.rollback_decision(dict(d, outcome="regression"))[0])
        for outcome in ("released", "nothing_to_release", "watchdog_disabled", "round_limit", "needs_human", "stuck",
                        "budget_exhausted", "time_limit", "crash", "provider_blocked"):
            self.assertFalse(rollback.rollback_decision(dict(d, outcome=outcome))[0], outcome)
        self.assertFalse(hasattr(run_module, "revert_main_to_base"))
        src = inspect.getsource(rollback.rollback_deploy)
        self.assertIn("ROLLBACK_WORKFLOW", src)
        self.assertNotIn('"git"', src)
        wf = yaml.safe_load((ROOT / "templates/starter/.github/workflows/rollback-fly.yml").read_text())
        self.assertIn("workflow_dispatch", wf[True])
        self.assertIn(".github/workflows/rollback-fly.yml", starter_template.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR, msg="template sync gives existing apps the workflow")
        self.assertTrue(run_audit.audit_report(dict(d, outcome="regression", stages=[], blocking=[], rollback={"status": "failed", "reason": "x"})))
        self.assertTrue(run_audit.audit_report(dict(d, outcome="round_limit", stages=[], blocking=[], revert={"status": "reverted"})))

    def test_inv26_a_child_that_ends_badly_and_every_other_failure_event_is_judged_and_handled_once(self):
        for outcome in ("round_limit", "needs_human", "stuck", "budget_exhausted", "time_limit", "crash", "watchdog_disabled"):
            self.assertTrue(lesson_records.wants_fix_request({"outcome": outcome}, {}), outcome)
        for outcome in ("released", "nothing_to_release"):
            self.assertFalse(lesson_records.wants_fix_request({"outcome": outcome}, {}), outcome)
        self.assertEqual((route.route("plan_gap"), route.route("spec_ambiguity"), route.route("infra"), route.route(None)), ("factory", "app", "info", "info"))
        self.assertEqual(route.route(route.inferred_category(None, "watchdog_disabled")), "app")
        self.assertEqual(factory_fix_request.fingerprint("a", "1", "factory"), factory_fix_request.fingerprint("a", "1", "factory"))
        self.assertNotEqual(factory_fix_request.fingerprint("a", "1", "factory"), factory_fix_request.fingerprint("a", "2", "factory"))
        gh = FakeIssues()
        ev = event.make("production_feedback", "failure", "demo", "TypeError in /api/todos", "fp")
        verdict = {"key": ev["key"], "verdict": "fix", "target": "managed_app", "cause": None, "reason": "r", "event": ev}
        doc = {"how_found": "a", "root_cause": "b", "what_it_takes": ["c"], "requirements": ["POST /api/todos answers 400 for blank text"], "source": "agent"}
        with mock.patch.object(github, "run", gh), mock.patch.object(github, "ensure_label"):
            first = file_bug.file_bug("o/f", "t", "pat", verdict, doc)
            second = file_bug.file_bug("o/f", "t", "pat", verdict, doc)
        self.assertEqual((first["action"], second["action"], second["number"]), ("bug_intake", "again", first["number"]), msg="the same event reported twice is one")

    FIX_FORM = "### App name\n\ndemo\n\n### What should change?\n\nChange set CS-1: T\n"

    def failed_child_tracker(self):
        gh = FakeIssues()
        gh.add(7)
        gh.add(12, body=child_tickets.render_marker({"parent": 7, "cs": "CS-1", "kind": "update", "flag": True}) + "\n\n" + self.FIX_FORM)
        gh.issues[12]["title"] = "demo: T"
        gh.subs[7] = [12]
        return gh

    def failure_verdict(self, story, fp):
        ev = event.make("build_run", "failure", "demo", "round limit", fp, story=story)
        return {"key": ev["key"], "verdict": "fix", "target": "managed_app", "cause": "spec_ambiguity", "reason": "r", "event": ev}

    def add_fix_child(self, gh, number, bug, attempt, of):
        marker = {"parent": bug, "cs": "CS-1", "kind": "update", "flag": True, "fix_for": of, "fix_attempt": attempt}
        gh.add(number, body=child_tickets.render_marker(marker) + "\n\n" + self.FIX_FORM, labels=["update-app-intake"])
        gh.issues[number]["title"] = "demo: fix"
        gh.subs[bug] = [number]

    def test_inv27_fix_first_never_retry_the_unchanged_child_and_bounded(self):
        self.assertEqual(PROFILES["limits"]["fix_attempts_max"], 2)
        gh = self.failed_child_tracker()
        doc = {"how_found": "a", "root_cause": "b", "what_it_takes": ["c"], "requirements": ["POST /api/todos answers 400 for blank text"], "source": "agent"}
        verdict, fix_child = self.failure_verdict, lambda *a: self.add_fix_child(gh, *a)
        with mock.patch.object(github, "run", gh), mock.patch.object(github, "ensure_label"):
            first = file_bug.file_bug("o/f", "t", "pat", verdict(12, "a"), doc, None, 2)
            fix_child(40, first["number"], 1, 12)
            second = file_bug.file_bug("o/f", "t", "pat", verdict(40, "b"), doc, None, 2)
            fix_child(41, second["number"], 2, 40)
            third = file_bug.file_bug("o/f", "t", "pat", verdict(41, "c"), doc, None, 2)
        self.assertEqual((first["action"], second["action"], third["action"]), ("bug_intake", "bug_intake", "needs_human"), msg="bounded along the fix_for chain")
        started = [c[2] for c in gh.calls if isinstance(c, list) and c[:2] == ["issue", "edit"] and "proceed-with-change" in c]
        self.assertNotIn("12", started, msg="the failed child itself is never started again as it was")
        self.assertEqual(gh.blocked[12], [first["number"]], msg="it waits for its bug Intake, which closes only with its last child")
        self.assertTrue(hasattr(resume_after_merge, "resume") and hasattr(close_child, "settle_fix"), msg="a Factory fix resumes it on merge; a bug Intake closing resumes it")

    def test_inv28_a_check_that_admits_it_was_not_observed_does_not_pass(self):
        real = "Unable to directly observe logs in production, but feature flag mechanism is working correctly"
        self.assertEqual(verify_deployed_app.check_state({"status": "passed", "evidence": real}), "not_run")
        self.assertFalse(verify_deployed_app.derive_test({"results": [{"flag": "a", "check": "x", "status": "passed", "evidence": real}]}, ["a"])[0])
        self.assertEqual(verify_deployed_app.check_state({"status": "passed", "evidence": "Status: 200"}), "passed")
        self.assertEqual(verify_deployed_app.check_state({"status": "passed", "evidence": "Cannot see logs, but npm run test:file shows 1 passed"}), "passed")

    def test_inv29_a_provider_with_no_balance_stops_the_run_and_retries_nothing(self):
        event = '{"code": "LLMBadRequestError", "detail": "OpenAIException - You need positive balance to do inference", "kind": "ConversationErrorEvent"}'
        self.assertTrue(provider.provider_blocked_text(event))
        self.assertFalse(provider.provider_blocked_text("the spec mentions a positive balance"))
        with mock.patch.object(http_client, "request", return_value=(402, {})):
            with self.assertRaises(run_stops.ProviderBlocked):
                provider.provider_check("https://x/v1", "k", "m")
            with self.assertRaises(run_stops.ProviderBlocked):
                spend_budget.Budget("admin", 1.0, 60).mint("m")
        self.assertFalse(lesson_records.wants_fix_request({"outcome": "provider_blocked"}, {}), msg="no self-starting retry")
        self.assertFalse(lesson_records.records_stuck_issue("provider_blocked"))
        self.assertNotIn("provider_blocked", outcomes.OK)

    def test_inv30_the_api_check_helpers_observation_outranks_the_testers_judgement(self):
        api = {"create": {"id": "create", "ok": False, "problems": ["status: expected 201, got 200"], "observed": {"status": 200}}}
        passed = {"flag": "f", "check": "create", "status": "passed", "passed": True, "evidence": "ok", "api": ["create"]}
        out = verify_deployed_app.reconcile_api_checks({"results": [passed]}, api)
        self.assertEqual(verify_deployed_app.check_state(out["results"][0]), "failed")
        self.assertEqual(verify_deployed_app.check_state(verify_deployed_app.reconcile_api_checks({"results": [passed]}, {})["results"][0]), "not_run")
        left_out = verify_deployed_app.reconcile_api_checks({"results": [{"flag": "f", "check": "x", "status": "passed", "passed": True, "evidence": "e"}]}, api)
        self.assertEqual(verify_deployed_app.check_state(left_out["results"][-1]), "failed")
        self.assertIsNotNone(ac.validate([{"id": "a", "request": {"path": "https://other.example/"}, "expect": {"status": 200}}])[1])

    def test_inv31_production_feedback_is_an_event_source_that_is_rate_limited_and_owner_only(self):
        cfg = {"min_occurrences": 3, "max_per_app_per_day": 2}
        groups = {"a" * 8: {"count": 9, "message": "m", "frame": ""}, "b" * 8: {"count": 8, "message": "n", "frame": ""},
                  "c" * 8: {"count": 1, "message": "o", "frame": ""}}
        self.assertEqual(flood_limits.decide(groups, {}, 0, 0, cfg)[0], ["a" * 8], msg="one at a time, below-threshold ignored")
        self.assertEqual(flood_limits.decide(groups, {}, 1, 0, cfg)[0], [], msg="one already open for the app")
        self.assertEqual(flood_limits.decide(groups, {}, 0, 2, cfg)[0], [], msg="the daily limit")
        self.assertEqual(flood_limits.decide(groups, {"a" * 8: 5}, 1, 0, cfg), ([], ["a" * 8]), msg="a repeat comments")
        issues = [{"number": 1, "title": "mine", "body": "", "author": {"login": "o"}}, {"number": 2, "title": "theirs", "body": "", "author": {"login": "someone"}}]
        with mock.patch.object(github, "run", lambda *a, **k: mock.Mock(stdout=json.dumps(issues))):
            self.assertEqual([i["number"] for i in escaped_defects.owner_defects("o/ai-factory", "pat", "demo")], [1], msg="a report by anyone but the owner is skipped")
        self.assertFalse(hasattr(scan_production, "file_update_app_intake"), msg="the scan reports events; Try Fix files the bug")

    def test_inv32_a_silent_agent_is_killed_long_before_the_overall_timeout(self):
        out = Path(tempfile.mkdtemp()) / "o.jsonl"
        rc = agent_process.run_watched([sys.executable, "-c", "import time; time.sleep(60)"], None, os.environ.copy(), out, 30, 1, poll=0.2)
        self.assertEqual(rc, "stall")
        self.assertGreater(PROFILES["limits"]["agent_stall_minutes"], 0)
        self.assertLess(PROFILES["limits"]["agent_stall_minutes"], PROFILES["limits"]["agent_timeout_minutes"])

    def test_inv33_template_sync_is_an_intake_for_agent_changeable_files_once_per_target(self):
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
        self.assertNotIn("push", triggers, msg="a merge to main never starts a Build Run: the nightly pass or a manual run does")
        self.assertIn("schedule", triggers)

    def test_inv34_agents_run_as_a_separate_account_and_the_run_proves_it(self):
        cmd = agent_process.agent_command(["openhands"], {"PATH": "/p", "LLM_API_KEY": "secret-jwt"}, "agent")
        self.assertEqual(cmd[:4], ["sudo", "-n", "-u", "agent"])
        self.assertNotIn("secret-jwt", " ".join(cmd))
        self.assertIn("GIT_CONFIG_VALUE_0", github.git_auth_env("h"))
        self.assertTrue(agent_process.isolation_problems({"whoami": "runner", "environ": "SELF-CHECK-SECRET", "workspace": "x", "env_names": "FACTORY_PAT", "sudo": "yes"}))
        self.assertEqual(PROFILES["limits"]["agent_isolation"], "user")

    def test_inv35_updates_reach_apps_only_as_gated_intakes(self):
        npm = {"number": 1, "title": "Bump a from 1 to 2", "url": "u", "headRefName": "dependabot/npm_and_yarn/a-2", "labels": []}
        acts = {"number": 2, "title": "Bump actions/checkout", "url": "u", "headRefName": "dependabot/github_actions/x", "labels": []}
        applicable, reported = mt.split_prs([npm, acts])
        self.assertEqual((applicable, reported), ([npm], [acts]))
        key = mt.update_key(applicable)
        self.assertTrue(mt.should_file(applicable, key, [], []))
        self.assertFalse(mt.should_file(applicable, key, [f"a: dependency updates [maint {key}]"], []))
        self.assertFalse(mt.should_file(applicable, key, [], [{"number": 9}]))
        self.assertEqual(set(starter_template.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR), {".github/dependabot.yml", ".github/workflows/test-gate.yml", ".github/workflows/rollback-fly.yml",
                                                                                              ".github/workflows/deploy-fly.yml"})

    def test_inv36_the_browser_helpers_observation_outranks_the_testers_judgement(self):
        ui = {"s": {"id": "s", "ok": False, "problems": ["role='button': expected it to be visible, but it is not"], "observed": {}}}
        passed = {"flag": "f", "check": "c", "status": "passed", "passed": True, "evidence": "e", "ui": ["s"]}
        self.assertEqual(verify_deployed_app.check_state(verify_deployed_app.reconcile_ui_checks({"results": [passed]}, ui)["results"][0]), "failed")
        self.assertEqual(verify_deployed_app.check_state(verify_deployed_app.reconcile_ui_checks({"results": [passed]}, {})["results"][0]), "not_run")
        self.assertEqual(verify_deployed_app.check_state(verify_deployed_app.reconcile_ui_checks({"results": [{**passed, "ui": []}]}, ui)["results"][-1]), "failed")
        self.assertIsNotNone(uc.validate([{"id": "a", "start": "https://other.example/", "expect": {"visible": [{"label": "x"}]}}])[1])
        self.assertNotIn("TKN-secret", uc.scrub("/?preview=TKN-secret and TKN-secret", "TKN-secret"))
        self.assertRegex((ROOT / "agents/playwright-version.txt").read_text().strip(), r"^\d+\.\d+\.\d+$")
        self.assertIn("playwright-version.txt", (ROOT / ".github/workflows/build-run.yml").read_text())

    def test_inv37_flags_are_retired_inside_an_update_run_only_when_proven(self):
        released = lambda slug, run, state="released": {"key": f"a.feature.{slug}", "date": "2026-10-01", "run_url": f"https://x/runs/{run}", "state": state}
        flags = [released("old", 1), released("older", 2), released("new", 9), released("dead", 3, "switched off by the watchdog")]
        got = retirement_selection.piggyback_slugs(flags, {"old", "older", "new", "dead"}, "2026-10-12", 1, 5)
        self.assertEqual(got, ["old", "older"], msg="oldest first; the newest release keeps its flag; a watchdog-off flag is dead, not retired")
        self.assertEqual(retirement_selection.piggyback_slugs(flags, {"old", "older", "new"}, "2026-10-12", 1, 1), ["old"])
        self.assertEqual(retirement_selection.piggyback_slugs(flags, {"old", "older", "new"}, "2026-10-01", 1, 5), [], msg="released today: not a day yet")
        self.assertEqual(retirement_check.retire_slugs(retirement_selection.retirement_block(["old", "older"])), ["old", "older"])
        self.assertIsNotNone(retirement_check.retirement_problem("old", retirement_check.code_references(['h:src/a.ts:3:  isFeatureEnabled(res, "old")'])))
        self.assertEqual(flag_manifest.removed_flag_slugs('[{"slug":"old"}]', "[]"), ["old"])
        self.assertGreaterEqual(PROFILES["limits"]["flag_retirement"]["piggyback_max"], 1)

    def test_inv38_a_flag_and_its_story_point_at_each_other(self):
        self.assertEqual(story_link.title_with_flags("app: a page", ["x"]), "app: a page [flag: x]")
        self.assertEqual(story_link.flag_label("x"), "flag:x")
        self.assertIn("issues/9", story_link.flag_description("https://github.com/o/r/issues/9", "t"))
        self.assertEqual(story_link.flag_tags(9, "app"), ["intake-9", "app-app"])
        self.assertIn("issues/9", app_state.story_link({"issue": 9, "run_url": "https://github.com/o/r/actions/runs/1"}))
        run = object.__new__(BuildRun)
        run.factory_repo, run.factory_token, run.issue, run.issue_title = "o/factory", "tok", "9", "app: a page"
        run.app, run.run_id, run.run_url = "app", "1", "https://github.com/o/factory/actions/runs/1"
        calls = []
        run.gh = lambda args, **k: calls.append(args)
        with mock.patch.object(github, "ensure_label"):
            run.link_flags_to_issue(["issue-9"])
        edits = [a for a in calls if a[:2] == ["issue", "edit"]]
        self.assertIn("flag:issue-9", [a[a.index("--add-label") + 1] for a in edits if "--add-label" in a])
        self.assertEqual(run.issue_title, "app: a page [flag: issue-9]", msg="the title carries the flag")
        self.assertIn("app.feature.issue-9", next(a for a in calls if a[:2] == ["issue", "comment"])[-1], msg="and a comment has the full key")

    def test_inv39_a_fix_is_one_ordinary_child_that_the_failed_child_waits_for(self):
        self.assertFalse(hasattr(fix_for, "apply"))
        self.assertEqual(fix_for.max_change_sets({"fix_for": 20}, 8), 1, msg="a bug Intake that fixes a child plans exactly one change set")
        self.assertEqual(fix_for.max_change_sets(None, 8), 8)
        for fn in ("release", "disable_flags"):
            self.assertTrue(hasattr(BuildRun, fn))

    def test_inv40_an_impossible_request_is_refused_before_anything_is_built(self):
        self.assertEqual(tr.find_secrets("key sk-" + "x1y2z3w4v5u6t7s8r9q0p1o2"), ["an API key (sk- style)"])
        self.assertEqual(tr.find_secrets("add a password field"), [])
        self.assertTrue(tr.feasibility({"feasibility": {"status": "blocked", "category": "payments", "reasons": ["card"]}})[0])
        self.assertFalse(tr.feasibility({"feasibility": {"status": "ok"}})[0])
        self.assertFalse(lesson_records.wants_fix_request({"outcome": "refused"}, {}))
        self.assertNotIn("refused", outcomes.OK)
        self.assertTrue(issubclass(endings.Refused, Exception))

    def test_inv41_a_model_swap_is_decided_by_a_measured_pass_and_survivable_at_run_time(self):
        base = {"tasks": 7, "passed": 6, "cost_usd": 2.0, "minutes": 100, "rounds_mean": 1.5,
                "by_task": {"refuse-secret": {"passed": True, "tags": ["refusal"], "outcome": "refused"}}}
        better = {"tasks": 7, "passed": 6, "cost_usd": 1.0, "minutes": 60, "rounds_mean": 1.4, "by_task": base["by_task"]}
        self.assertTrue(bm.compare(better, base)["accept"] and bm.compare(better, base)["improvement"])
        careless = {**better, "by_task": {"refuse-secret": {"passed": False, "tags": ["refusal"], "outcome": "released"}}}
        self.assertFalse(bm.compare(careless, base)["accept"], msg="cheaper, but it stopped refusing")
        self.assertFalse(bm.compare({**better, "cost_usd": 3.0}, base)["accept"])
        text = (ROOT / "agents/profiles.yml").read_text()
        doc = yaml.safe_load(bm.candidate_profile(text, {"coder": "x/y"}))
        self.assertEqual((doc["roles"]["coder"]["model"], doc["limits"]["flag_retirement"]["piggyback_max"]), ("x/y", 0))
        run = object.__new__(BuildRun)
        run.cfg = {"provider": {"base_url": "u"}, "roles": {"coder": {"model": "gone", "fallback_model": "ok"}}}
        run.state = track_progress.State(Path("/tmp/inv41-state.json"), "a", "1", "u")
        run.state.save = lambda: None
        with mock.patch.object(http_client, "request", lambda m, u, t=None, body=None, timeout=60: (404, {}) if body["model"] == "gone" else (200, {})), \
                mock.patch.dict(os.environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertEqual(run.cfg["roles"]["coder"]["model"], "ok")

    def test_inv42_only_reviewed_code_is_pushed_and_the_reviewer_runs_before_the_push(self):
        self.assertNotIn('"push"', inspect.getsource(BuildRun.coder), msg="the coder only commits")
        deploy_src = inspect.getsource(BuildRun.review_and_deploy)
        self.assertLess(deploy_src.index("review_before_push"), deploy_src.index("push_through_pipeline"))
        self.assertLess(*[inspect.getsource(BuildRun.play_round).index(name) for name in ("review_and_deploy", "test_until_decided")])
        self.assertIn("PipelineFix", inspect.getsource(BuildRun.push_through_pipeline), msg="a fix CI needed is reviewed again before it is pushed")
        t = RoundLoop()
        run = t.make([t.BLOCKED, t.CLEAN], [t.PASSED])
        t.go(run)
        self.assertNotIn("push c1", run.calls)
        self.assertLess(run.calls.index("review c2"), run.calls.index("push c2"))

    def test_inv43_a_dark_feature_is_removed_only_after_the_retries_and_a_persons_approval(self):
        ready = ["update-app-intake", "app:notes", "flag:pin", "dark-broken", "needs-human"]
        self.assertEqual(dark_feature.dark_removal_target(ready), ("notes", "pin", None))
        for missing in ("dark-broken", "needs-human"):
            self.assertIsNotNone(dark_feature.dark_removal_target([l for l in ready if l != missing])[2])
        wf = yaml.safe_load((ROOT / ".github/workflows/approve-retire.yml").read_text())
        self.assertEqual(wf[True]["issues"]["types"], ["labeled"])
        self.assertIn("approve-retire", wf["jobs"]["approve"]["if"])
        d = {"flags": ["pin"], "commits": ["h"], "outcome": "round_limit"}
        self.assertTrue(dark_feature.is_dark_broken(d), msg="a run that stops marks the feature; nothing deletes it")
        self.assertTrue(dark_feature.is_dark_broken(dict(d, outcome="regression")), msg="rolled back, but its code stays in main behind the flag")
        self.assertFalse(dark_feature.is_dark_broken(dict(d, outcome="released")))

    def test_inv44_the_tester_says_what_a_failure_means_and_only_what_a_helper_saw_is_a_regression(self):
        new_check = {"flag": "f", "check": "c", "status": "failed", "scope": "new", "api": ["a"]}
        old_check = {"flag": "", "check": "c", "status": "failed", "scope": "existing", "api": ["a"]}
        self.assertEqual((verify_deployed_app.test_impact([]), verify_deployed_app.test_impact([new_check]), verify_deployed_app.test_impact([old_check])), ("ok", "dark_only", "regression"))
        self.assertEqual(verify_deployed_app.test_impact([dict(old_check, api=[], ui=[])]), "dark_only")
        self.assertEqual(verify_deployed_app.test_impact([dict(old_check, status="blocked")]), "dark_only")
        doc = {"improvements": [{"target": "factory", "summary": "x", "evidence": ""}, {"target": "other", "summary": "y"}]}
        self.assertEqual([i["target"] for i in suggestions.improvements_from(doc, "tester")], ["factory"], msg="the Agents suggest; they file nothing")
        self.assertTrue(hasattr(story_report, "note_bugs_on_story") and not hasattr(story_report, "record_bugs"), msg="bugs go on the story, never a new issue")
        self.assertGreaterEqual(len(tracker.content_words("Coder prompt does not say to trim the input") & tracker.content_words("The coder prompt never says to trim input")), 4)

    def test_inv45_the_retrospective_agent_is_isolated_like_the_build_run_agents(self):

        src = inspect.getsource(agent_run.run_agent)
        self.assertIn("run_isolation_probes", src)
        self.assertIn("user=user", src)
        self.assertIn("apply_changes", inspect.getsource(agent_run.carry_over_changes))
        self.assertNotIn("subprocess.run", src)
        self.assertNotIn('"git"', inspect.getsource(agent_run.run_tests) + inspect.getsource(agent_run.tree_changes) + inspect.getsource(agent_run.apply_changes))
        self.assertIn("run_tests(", inspect.getsource(learning_pr.proposal_passes_tests))
        self.assertNotIn("unittest", inspect.getsource(learning_pr.open_pr).replace("run_tests", ""))
        for name in ("build-run.yml", "factory-run.yml"):
            text = (ROOT / ".github/workflows" / name).read_text()
            self.assertIn("useradd -m -s /bin/bash agent", text, name)
            self.assertIn("AGENT_USER=agent", text, name)
        self.assertEqual(agent_run.tree_changes.__module__, "retrospective.agent_run")

    def test_inv46_what_blocks_or_retries_is_decided_from_structure_not_labels(self):
        self.assertFalse(review_code.derive_review({"findings": [finding()]})[0])
        for weak in (finding(evidence_kind="opinion"), finding(category="style"), finding(file="", line="")):
            self.assertTrue(review_code.derive_review({"findings": [weak]})[0])
        found = review_code.flag_findings(lambda *a: json.dumps([{"slug": "s", "description": "none"}]) if a[0] == "show" else "", "head", ["s"])
        self.assertEqual({f["severity"] for f in found}, {"minor"})
        failed = {"flag": "f", "check": "c", "status": "failed"}
        self.assertEqual(verify_deployed_app.failed_checks([failed, {"status": "blocked"}, {"status": "not_run"}]), [failed])
        t = RoundLoop()
        run = t.make([t.CLEAN], [t.UNVERIFIED_BLOCKED, t.UNVERIFIED_BLOCKED])
        t.go(run)
        self.assertEqual(run.state.d["outcome"], "needs_human")
        self.assertEqual(run.calls.count("coder2"), 0, msg="no coder round for checks nobody could run")

    def test_inv47_the_lint_config_is_the_orchestrators_and_a_stricter_rule_never_reaches_main_alone(self):
        for f in ("eslint.config.mjs", ".prettierrc.json", ".prettierignore"):
            self.assertEqual(starter_template.protected_violations([f]), [f], msg="a coder commit that touches it is rejected")
            self.assertIn(f, starter_template.TEMPLATE_FILES_HELD)
            self.assertTrue((ROOT / "templates/starter" / f).is_file(), f)
        self.assertEqual(set(starter_template.TEMPLATE_FILES_OWNED_BY_ORCHESTRATOR), set(starter_template.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR) | set(starter_template.TEMPLATE_FILES_HELD))
        src = inspect.getsource(BuildRun.prepare_checkout)
        self.assertLess(src.index("apply_template_files(labels)"), src.index('self.state.d["base_sha"]'))
        self.assertLess(src.index('self.state.d["base_sha"]'), src.index("stage_template_config(labels)"))
        self.assertNotIn('"push"', inspect.getsource(BuildRun.stage_template_config) + inspect.getsource(BuildRun.copy_template_files))
        found = review_code.suppression_findings(lambda *a: "+++ b/backend/src/a.ts\n@@ -1 +1 @@\n+// eslint-disable-next-line\n", "base", "head")
        self.assertEqual([f["severity"] for f in found], ["minor"])
        cases = json.loads((ROOT / "agents/lint-fixtures/cases.json").read_text())["cases"]
        self.assertTrue(any(c["expect"] for c in cases) and any(not c["expect"] for c in cases), msg="failing and passing cases exist")


    def secrets_run(self, listed):
        run = object.__new__(BuildRun)
        run.app_repo, run.issue, run.factory_repo, run.factory_token = "o/app", "7", "o/f", "tok"
        run.state = mock.Mock(d={})
        run.gh = lambda args, token=None, check=True: mock.Mock(returncode=0, stdout=json.dumps(listed) if args[:2] == ["secret", "list"] else "")
        return run

    def assert_declared_secrets_round_trip(self, need):
        marker = secrets_marker.secrets_marker(need)
        self.assertEqual(secrets_marker.declared_secrets({"comments": [{"body": "text\n\n" + marker}]}), need)
        child = render_child.child_body("app", "task", 5, {"id": "CS-1"}, [], secrets=need)
        self.assertEqual(secrets_marker.declared_secrets({"body": child, "comments": []}), need)
        self.assertEqual(secrets_marker.declared_secrets({"body": "no marker", "comments": []}), [])

    def assert_awaiting_secret_is_an_answer_not_a_failure(self, need):
        self.assertIn("awaiting_secret", outcomes.ANSWERED)
        self.assertNotIn("awaiting_secret", outcomes.OK, msg="INV-24: an OK ending closes the Intake")
        self.assertFalse(lesson_records.wants_fix_request({"outcome": "awaiting_secret"}, {}))
        self.assertFalse(lesson_records.records_stuck_issue("awaiting_secret"))
        self.assertNotIn("-----", triage.secrets_request(need, "o/app"))

    def test_inv48_a_request_needing_a_secret_builds_nothing_until_its_names_exist(self):
        listed = [{"name": "OTHER"}]
        run = self.secrets_run(listed)
        need = [{"name": "WEATHER_API_KEY", "purpose": "forecast lookups"}]
        with self.assertRaises(endings.AwaitingSecret) as cm:
            run.require_secrets(need)
        self.assertIn("WEATHER_API_KEY", str(cm.exception), msg="the command itself is posted by planning (plan_run.py), not here")
        self.assertEqual(run.state.d["secrets"], ["WEATHER_API_KEY"])
        listed.append({"name": "WEATHER_API_KEY"})
        run.require_secrets(need)
        self.assert_declared_secrets_round_trip(need)
        src = __import__("inspect").getsource(BuildRun.read_request)
        self.assertIn("secrets_marker.declared_secrets(issue)", src)
        self.assertLess(src.index("require_secrets(self.declared_secrets)"), src.index("self.spec = self.task"))
        listed.clear()
        with self.assertRaises(endings.AwaitingSecret):
            run.require_secrets(need)
        self.assert_awaiting_secret_is_an_answer_not_a_failure(need)

    def assert_secret_value_is_discarded(self, run):
        calls = []

        def git(*a, check=True, cwd=None):
            calls.append(a)
            if a[0] == "diff":
                return mock.Mock(stdout="+++ b/x.ts\n+const k = \"sk-" + "a" * 30 + "\";\n")
            return mock.Mock(returncode=0, stdout="")
        run.git = git
        problem = run.secret_problem("base", "head")
        self.assertIn("API key", problem)
        self.assertNotIn("sk-a", problem)
        self.assertIn(("reset", "-q", "--hard", "base"), calls)

    def test_inv49_a_commit_with_a_secret_value_or_an_undeclared_name_is_never_pushed(self):
        run = object.__new__(BuildRun)
        run.state = mock.Mock(d={"secrets": ["WEATHER_API_KEY"]})
        self.assert_secret_value_is_discarded(run)
        self.assertIsNotNone(triage.secret_name_problem("FLY_API_TOKEN"))
        self.assertIsNotNone(triage.secret_name_problem("GITHUB_TOKEN"))
        self.assertIsNone(triage.secret_name_problem("WEATHER_API_KEY"))
        run.git = lambda *a, check=True, cwd=None: mock.Mock(
            returncode=0 if not (a[0] == "show" and a[1].startswith("base:")) else 1,
            stdout="+++ b/x\n+ok\n" if a[0] == "diff" else json.dumps({"secrets": [{"name": "SNEAKY_KEY"}]}))
        self.assertIn("SNEAKY_KEY", run.secret_problem("base", "head"))
        run.git = lambda *a, check=True, cwd=None: mock.Mock(returncode=0, stdout="+++ b/x\n+ok\n" if a[0] == "diff" else json.dumps({"secrets": [{"name": "SNEAKY_KEY"}]}))
        self.assertIsNone(run.secret_problem("base", "head"))
        deploy = (STARTER / ".github/workflows/deploy-fly.yml").read_text()
        self.assertIn("flyctl secrets import --stage", deploy)
        self.assertIn("reserved", deploy)
        self.assertTrue((STARTER / "secrets.json").is_file())

    def test_inv50_no_secret_value_reaches_an_issue_a_command_line_or_an_agent(self):
        deploy = (STARTER / ".github/workflows/deploy-fly.yml").read_text()
        step = deploy[deploy.index("Sync the app's own secrets"):deploy.index("Copy image from GHCR")]
        self.assertIn("< /tmp/app-secrets", step, msg="the values go to Fly through stdin")
        self.assertNotIn("toJSON(secrets)", deploy, msg="GitHub flags a workflow that dumps the whole secrets context as malicious and will not run it")
        wired = prepare_run.wire_secrets(deploy, ["WEATHER_API_KEY", "FLY_API_TOKEN", "bad name"])
        self.assertIn("WEATHER_API_KEY: ${{ secrets.WEATHER_API_KEY }}", wired, msg="an ordinary static reference")
        self.assertNotIn("secrets.FLY_API_TOKEN: ", wired.split("factory-secrets:begin")[1].split("factory-secrets:end")[0])
        self.assertEqual(prepare_run.wire_secrets(wired, ["WEATHER_API_KEY"]), wired, msg="idempotent")
        self.assertEqual(prepare_run.wire_secrets(wired, []), deploy, msg="and removable")
        self.assertNotIn("echo \"$value\"", step)
        self.assertEqual(triage.find_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"), ["a bearer or JWT token"])


    def test_inv51_a_flags_name_is_issue_n_of_its_story_and_it_exists_off_before_the_coder_starts(self):
        cs = {"id": "CS-1", "title": "T", "criteria": ["AC-1: x"], "verification": ["v"], "flag": True}
        self.assertIn(flag_slug.SLOT, render_child.render_change_set_task(cs))
        self.assertEqual(flag_slug.for_story(42), "issue-42")
        gb = FakeGrowthBook({"demo.feature.old": {"environments": {"production": {"enabled": True, "rules": []}}}})
        self.assertTrue(flag_slug.ensure_feature(gb, "demo", "issue-42", "https://github.com/o/f/issues/42", "t", "42"))
        self.assertFalse(gb.production_enabled("demo.feature.issue-42"), msg="dark until the gates pass")
        self.assertFalse(flag_slug.ensure_feature(gb, "demo", "old", "u", "t", "1"), msg="an existing flag is never touched")
        self.assertTrue(gb.production_enabled("demo.feature.old"))
        self.assertIn("issue-42", flag_slug.add_to_manifest("[]", "issue-42", "o/f#42", "t"))

    def test_inv52_a_flag_that_does_not_exist_at_release_is_reported_not_made_up(self):
        gb = FakeGrowthBook()
        self.assertEqual(release_features.check_flags(gb, "demo", ["ghost"], ["ghost"]), ([], [], ["ghost"]))
        self.assertEqual(gb.features, {}, msg="nothing was created")
        self.assertEqual(missing_flag.split(["read", "unread"], lambda s: s == "read"), (["read"], ["unread"]))
        self.assertNotIn(outcomes.FLAG_MISSING, outcomes.OK)
        self.assertFalse(rollback.rollback_decision({"outcome": outcomes.FLAG_MISSING})[0], msg="dark: nothing to roll back")
        self.assertTrue(rollback.rollback_decision({"outcome": "regression", "head_sha": "h", "base_sha": "g", "commits": ["h"]})[0], msg="live and failing")
        self.assertIn("A flag that can be turned on has to exist", missing_flag.dark_message(["x"], None))
        self.assertIn("left as it is", missing_flag.live_message(["x"], None, False))
    def test_inv53_every_flag_is_tested_both_ways_before_review_and_a_retirement_removes_the_tests(self):
        self.assertEqual(starter_template.protected_violations(["scripts/check-flags.mjs"]), ["scripts/check-flags.mjs"])
        self.assertIn("scripts/check-flags.mjs", starter_template.TEMPLATE_FILES_HELD)
        self.assertIn("check-flags.mjs", json.loads((STARTER / "package.json").read_text())["scripts"]["check"])
        self.assertTrue((STARTER / "backend/src/__tests__/with-flag.ts").is_file())
        if shutil.which("node"):
            run = lambda files: json.loads(subprocess.run(["node", str(STARTER / "scripts/check-flags.mjs"), "--stdin"], capture_output=True, text=True,
                                                          input=json.dumps({"slugs": ["issue-1"], "files": files})).stdout)
            self.assertEqual(len(run({"backend/src/x.test.ts": "it('x', () => {});"})), 2, msg="neither test: both reported")
        hits = retirement_check.code_references(['h:flags.json:2:  "slug": "issue-1",', 'h:backend/src/x.test.ts:4:  withFlag("issue-1", false, f)'])
        self.assertEqual(len(hits), 2, msg="tests and the manifest count, not only source")

    def test_inv54_a_plan_is_rolled_back_as_one_and_its_children_are_filed_once_or_not_at_all(self):
        cs = {"id": "CS-1", "title": "T", "requirements": ["REQ-1"], "depends_on": [], "criteria": ["AC-1: x"], "verification": ["v"], "size": "S",
              "flag": True, "internal_only": False, "out_of_scope": []}
        plan = {"requirements": [{"id": "REQ-1", "text": "t"}], "assumptions": [], "open_questions": [], "change_sets": [cs]}
        self.assertEqual(validate_plan.validate_plan(plan, "update"), ([], []))
        for bad in (dict(cs, size="L"), dict(cs, criteria=["AC-1: x"] * 7), dict(cs, kind="staging", flag=None), dict(cs, criteria=["AC-1: needs CS-2"])):
            self.assertTrue(validate_plan.validate_plan(dict(plan, change_sets=[bad]), "update")[0], bad)
        self.assertTrue(validate_plan.validate_plan(plan, "first build")[0], msg="a new app starts with its staging change set")
        gh = FakeIssues()
        gh.add(7)
        tickets = child_tickets.ChildTickets("o/f", 7, "pat", gh)
        args = ("o/f", "pat", "app", 7, [cs, dict(cs, id="CS-2", depends_on=["CS-1"])], ["CS-1", "CS-2"], "r")
        with mock.patch.object(file_children.github, "run", gh):
            made = file_children.file_children(*args, tickets=tickets)
            self.assertEqual(file_children.file_children(*args, tickets=tickets), made, msg="filed once")
        self.assertEqual(len(gh.subs[7]), 2)
        self.assertEqual(len(gh.blocked), 1)

    def test_inv55_a_build_run_starts_only_for_a_planned_child_of_an_open_plan(self):
        marker = {"parent": 7, "cs": "CS-1", "kind": "update"}
        self.assertIsNone(read_child.planned_problem(marker, {"number": 7, "state": "OPEN"}))
        for bad in (({}, {"number": 7, "state": "OPEN"}), (marker, None), (marker, {"number": 7, "state": "CLOSED"}), (marker, {"number": 8, "state": "OPEN"})):
            self.assertTrue(read_child.planned_problem(*bad), bad)
        self.assertTrue(read_child.planned_problem({"parent": 7, "kind": "staging"}, {"number": 7, "state": "OPEN"}), msg="a staging child is never a Build Run")

    def assert_plan_workflow_skips_children(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/plan.yml").read_text())
        cond = " ".join(next(iter(wf["jobs"].values()))["if"].split())
        self.assertIn("update-app-intake", cond)
        self.assertIn("factory-plan", cond, msg="never a child")
        self.assertIn("plan-", wf["concurrency"]["group"])

    def test_inv56_planning_is_its_own_process_that_files_a_child_and_can_always_be_retried(self):
        self.assert_plan_workflow_skips_children()
        gh = FakeIssues()
        gh.add(7)
        comments = []
        doc = {"feasibility": {"status": "ok"}, "requirements": [{"id": "REQ-1", "text": "t"}], "assumptions": [], "open_questions": [], "secrets": [],
               "change_sets": [{"id": "CS-1", "title": "T", "requirements": ["REQ-1"], "depends_on": [], "criteria": ["AC-1: x"], "verification": ["v"],
                                "size": "S", "flag": True, "internal_only": False, "out_of_scope": []}]}
        intake = {"kind": "update", "app": "notes", "task": "t", "cap": 2.0, "cap_override": None, "declared": [], "label": "update-app-intake"}
        tickets = ct.ChildTickets("o/f", 7, "pat", gh)
        run = lambda d: plan_run.PlanRun(7, intake, {}, lambda task: (d, 0.0, None), comments.append, lambda: set(), tickets,
                                         lambda parent, sets, order, secrets: [(c["id"], 100) for c in sets]).run()
        self.assertEqual(len(run(doc)["children"]), 1, msg="even one change set is a child")
        stopped = run(dict(doc, open_questions=[{"id": "Q-1", "text": "?", "blocking": True}]))
        self.assertEqual(stopped["ending"], "needs_human")
        self.assertIn("remove the `update-app-intake` label and add it again", comments[-1])
        self.assertNotIn("planned", outcomes.OK, msg="a Build Run never ends by planning")
        self.assertFalse(hasattr(BuildRun, "plan_change"))

    def test_inv57_a_staging_child_is_verified_by_deterministic_checks_before_anything_is_built_on_it(self):
        self.assertEqual(verify_infrastructure.CHECKS, ("ci_green", "deploy_healthy", "flag_service", "preview_token", "secrets_present", "smoke"))
        wf = (ROOT / ".github/workflows/update-app-intake.yml").read_text()
        self.assertIn("!contains(github.event.issue.body, '\"kind\":\"staging\"')", wf)
        marker = child_tickets.render_marker({"parent": 7, "cs": "CS-1", "kind": "update"})
        with self.assertRaises(read_staging_child.NotStageable):
            read_staging_child.check_child({"body": marker + "\n\n### App name\n\nnotes\n"}, {"number": 7, "state": "OPEN"}, {"body": ""}, [], 0, 1, PROFILES["limits"])
        self.assertEqual(read_staging_child.staging_children_in_flight([{"number": 3, "body": child_tickets.render_marker({"kind": "staging"})}], 4), [3])
        script = (ROOT / "infra/app-staging/stage.sh").read_text()
        self.assertIn("staging.verify_infrastructure", script)
        self.assertLess(script.index("staging.verify_infrastructure"), script.index("retrospective.close_child close"), msg="verified, then the next child starts")
    def test_inv58_every_failure_event_gets_a_verdict_a_failure_is_never_downgraded_and_a_warning_needs_a_reason(self):
        failure = event.make("build_run", "failure", "demo", "round limit", "f")
        warning = event.make("tester", "warning", "demo", "a dark check failed", "w")
        entries = {failure["key"]: {"key": failure["key"], "verdict": "record", "reason": "skip"}, warning["key"]: {"key": warning["key"], "verdict": "fix"}}
        got = {v["key"]: v for v in event_verdicts.decide([failure, warning], entries)}
        self.assertEqual(set(got), {failure["key"], warning["key"]}, msg="one verdict for every event")
        self.assertEqual(got[failure["key"]]["verdict"], "fix", msg="the Agent cannot downgrade a failure")
        self.assertEqual(got[warning["key"]]["verdict"], "record")
        self.assertEqual(event_verdicts.decide([warning], {warning["key"]: {"key": warning["key"], "verdict": "fix", "reason": "users wait"}})[0]["verdict"], "fix")
        facts = {"app": "demo", "outcome": "stuck", "message": "m", "issue_number": "1", "flags": [], "final_minor": [{"summary": "s"}]}
        self.assertEqual([e["severity"] for e in collect_events.from_run(facts, "fp")], ["failure", "warning"])
        self.assertTrue(lesson_records.wants_fix_request({"outcome": "stuck"}, {}))

    def test_inv59_the_try_fix_agent_only_writes_the_ticket_text_and_its_answer_is_validated_or_replaced(self):
        ev = event.make("tester", "failure", "demo", "blank text accepted", "fp")
        verdict = {"key": ev["key"], "verdict": "fix", "target": "managed_app", "cause": "spec_ambiguity", "reason": "r", "event": ev}
        cfg = {**PROFILES, "limits": {**PROFILES["limits"], "planner_max_criteria": 6}}
        prompt = (ROOT / "agents" / PROFILES["roles"]["try_fix"]["prompt"]).read_text()
        self.assertIn("You do not decide the cause or the target, and you do not plan", prompt)
        good = {"how_found": "The tester saw it.", "root_cause": "No trimming.", "what_it_takes": ["Blank text is rejected"],
                "requirements": ["POST /api/todos with blank text answers 400"], "target": "factory", "children": ["a", "b"]}
        got = write_bug.write(verdict, None, None, cfg, "k", lambda *a, **k: good)
        self.assertEqual(set(got), {"how_found", "root_cause", "what_it_takes", "requirements", "source"}, msg="it never carries a target or a plan")
        for vague in ({"how_found": "x"}, {**good, "requirements": ["Improve validation of todos"]}, {**good, "root_cause": "key ghp_" + "a1" * 15}):
            self.assertEqual(write_bug.write(verdict, None, None, cfg, "k", lambda *a, _v=vague, **k: _v)["source"], "fallback", msg="replaced, never filed as is")
        self.assertEqual(validate_bug.check(write_bug.fallback(verdict, None, None), 6)[1], [])
        self.assertTrue(render_bug.intake_body("demo", got, verdict).startswith(render_bug.marker(ev["key"])))
        form = yaml.safe_load((ROOT / ".github/ISSUE_TEMPLATE/bug.yml").read_text())
        self.assertEqual(form["labels"], ["bug", "update-app-intake"], msg="a bug is planned like any Update App Intake")


    def test_inv60_a_bug_is_dark_or_released_by_the_flags_state_and_only_a_dark_story_makes_its_child_wait(self):
        state = {"flags": [{"key": "demo.feature.issue-12", "state": "released"}, {"key": "demo.feature.issue-20", "state": "switched off by the watchdog"}]}
        states = route_bug.flag_states(state)
        self.assertEqual((states[12], states[20]), ("released", "dark"), msg="a flag the watchdog switched off is dark (STEP 5.5)")
        form = "### App name\n\ndemo\n\n### What should change?\n\nChange set CS-1: T\n"
        doc = {"how_found": "a", "root_cause": "b", "what_it_takes": ["c"], "requirements": ["POST /api/todos answers 400 for blank text"], "source": "agent"}
        for released, waits in ((False, True), (True, False)):
            gh = FakeIssues()
            gh.add(7)
            gh.add(20, body=child_tickets.render_marker({"parent": 7, "cs": "CS-1", "kind": "update", "flag": True}) + "\n\n" + form)
            gh.issues[20]["title"] = "demo: T"
            gh.subs[7] = [20]
            ev = event.make("production_feedback", "failure", "demo", "TypeError", "fp", story=20, released=released)
            verdict = {"key": ev["key"], "verdict": "fix", "target": "managed_app", "cause": None, "reason": "r", "event": ev}
            with mock.patch.object(github, "run", gh), mock.patch.object(github, "ensure_label"):
                got = file_bug.file_bug("o/f", "t", "pat", verdict, doc)
            self.assertEqual(bool(child_tickets.read_fix_for(gh.issues[got["number"]]["body"])), waits, msg="dark: fix_for and the failed child waits; released: a regression, no marker, nothing waits")
            self.assertEqual(bool(gh.blocked), waits)

    def test_inv61_a_child_is_routed_by_the_kind_in_its_marker_to_staging_or_to_a_build_run_never_both(self):
        staging, update = (" ".join(next(iter(yaml.safe_load((ROOT / ".github/workflows" / n).read_text())["jobs"].values()))["if"].split())
                           for n in ("app-staging.yml", "update-app-intake.yml"))
        kind = '"kind":"staging"'
        self.assertIn(kind, child_tickets.render_marker({"kind": "staging"}), msg="the text the workflows match is the text the planner writes")
        self.assertIn(f"contains(github.event.issue.body, '{kind}')", staging)
        self.assertIn(f"!contains(github.event.issue.body, '{kind}')", update)

    def test_inv62_a_pipeline_failure_is_diagnosed_and_its_retries_and_coder_fixes_are_bounded(self):

        self.assertGreaterEqual(PROFILES["limits"]["pipeline_retries"], 0)
        self.assertGreater(PROFILES["limits"]["pipeline_fix_attempts"], 0)
        source = inspect.getsource(ship_code)
        for bound in ("pipeline_retries", "pipeline_fix_attempts", "NOT_STARTED_CONCLUSIONS"):
            self.assertIn(bound, source)


class Registry(unittest.TestCase):
    def test_inv63_a_factory_change_outside_its_scope_or_limits_is_refused(self):
        limits = {"factory_change_max_files": 2, "factory_change_max_added_lines": 10}
        touched = {"status": "M", "added": 1, "deleted": 0}
        for path in (".github/workflows/factory-checks.yml", "orchestrator/style_baseline.json", "pyproject.toml", "README.md"):
            self.assertIsNotNone(vet_change.problem({path: touched}, limits), path)
        self.assertIsNotNone(vet_change.problem({"orchestrator/bugs/a.py": touched, "orchestrator/try_fix/b.py": touched}, limits))
        self.assertIsNotNone(vet_change.problem({"orchestrator/a_test.py": {"status": "D", "added": 0, "deleted": 4}}, limits))
        self.assertIsNotNone(vet_change.problem({"agents/profiles.yml": touched}, limits, {"agents/profiles.yml": "+  model: x\n"}))
        self.assertIsNone(vet_change.problem({"orchestrator/bugs/a.py": touched}, limits))
        profiles = yaml.safe_load((ROOT / "agents/profiles.yml").read_text(encoding="utf-8"))["limits"]
        self.assertTrue({"factory_change_max_files", "factory_change_max_added_lines", "max_open_factory_change_prs"} <= set(profiles))

    def test_inv66_a_factory_change_is_a_pull_request_and_merges_itself_only_outside_the_control_path_after_every_gate(self):
        self.assertNotIn("HEAD:main", inspect.getsource(open_pr))
        self.assertNotIn("push", inspect.getsource(open_pr.open_pr).replace("push_branch", ""))
        self.assertEqual(open_pr.branch_of(7), "factory-change/7")
        self.assertEqual(tiers.merge_tier(["orchestrator/bugs/a.py"]), tiers.TIER_ONE)
        self.assertNotEqual(tiers.merge_tier(["orchestrator/bugs/a.py", "orchestrator/try_fix/b.py"]), tiers.TIER_ONE)
        self.assertEqual(open_pr.labels_for(tiers.TIER_TWO), [open_pr.PR_LABEL, open_pr.HOLD_LABEL])
        job = yaml.safe_load((ROOT / ".github/workflows/factory-checks.yml").read_text())["jobs"]["factory-change-merge"]
        self.assertEqual(set(job["needs"]), {"unit", "starter", "reviewer-smoke", "factory-change-gate"})
        steps = [s.get("run", "") for s in job["steps"]]
        self.assertLess(next(i for i, r in enumerate(steps) if "gate merge-check" in r), next(i for i, r in enumerate(steps) if "gh pr merge" in r))
        self.assertIn("startsWith(github.head_ref, 'factory-change/')", job["if"])
        self.assertIn("merge-check", inspect.getsource(gate.main))

    def test_inv64_a_reproduction_has_to_fail_on_main_before_any_agent_runs(self):
        for bad in ("-k", "--help", "../x.y", "x"):
            self.assertFalse(prove_reproduction.valid_name(bad), bad)
        self.assertEqual(prove_reproduction.classify_run(0, "OK"), "passes")
        self.assertEqual(prove_reproduction.classify_run(1, "FAIL: test_it (m.C.test_it)"), "fails")
        self.assertEqual(prove_reproduction.classify_run(1, "ModuleNotFoundError: no m\nERROR: m (unittest.loader._FailedTest)"), "missing")
        problems = file_change.ticket_problems("## Observable failure\nx\n## Requirements\n1. Every child is filed under the Intake\n## Reproduction\nnot a test", 8)
        self.assertEqual(len(problems), 1)

    def test_inv65_an_open_paused_issue_stops_the_factory_change_process(self):
        gh = FakeIssues()
        with mock.patch.object(github, "run", gh):
            pause.pause("o/f", "t", "a regression")
            self.assertTrue(pause.is_paused("o/f", "t"))
            filed = file_change.file_change("o/f", "t", {"fingerprint": "ab", "summary": "s", "failure": "f", "requirements": ["Every child is filed under the Intake"], "evidence": "e"}, 8)
        self.assertEqual(filed["action"], "paused")
        self.assertIsNotNone(pause.breaker_reason("review", [{"failed": True, "stage": "review"}], 0))
        self.assertIsNotNone(pause.breaker_reason("review", [{"regression": True}], 0))
        self.assertIsNotNone(pause.breaker_reason("review", [], 2))

    def test_the_table_and_the_tests_list_the_same_invariants(self):
        table = set(re.findall(r"^\| INV-(\d\d) \|", (ROOT / "docs/invariants.md").read_text(), re.M))
        tests = set(re.findall(r"def test_inv(\d\d)_", Path(__file__).read_text(encoding="utf-8")))
        self.assertEqual(table - tests, set(), "invariants with no test")
        self.assertEqual(tests - table, set(), "tests for invariants that are not in docs/invariants.md")
        self.assertTrue(table)


if __name__ == "__main__":
    unittest.main()
