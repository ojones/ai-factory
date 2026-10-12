"""Unit tests for the Build Run's deterministic logic. Run: python3 -m unittest discover orchestrator"""
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402

FORM = ("### What should be built?\r\n\r\nA notes app\r\nwith tags\r\n\r\n"
        "### Cost cap override (USD)\r\n\r\n{cap}\r\n")


class Intake(unittest.TestCase):
    def test_default_cap(self):
        task, cap = b.parse_intake(FORM.format(cap="_No response_"), 2.0, 10.0)
        self.assertEqual((task, cap), ("A notes app\nwith tags", 2.0))

    def test_override_with_dollar_sign(self):
        self.assertEqual(b.parse_intake(FORM.format(cap="$3.5"), 2.0, 10.0)[1], 3.5)

    def test_rejects_over_ceiling_zero_and_garbage(self):
        for bad in ("10.01", "0", "abc"):
            with self.assertRaises(b.NeedsHuman):
                b.parse_intake(FORM.format(cap=bad), 2.0, 10.0)

    def test_rejects_empty_task(self):
        with self.assertRaises(b.NeedsHuman):
            b.parse_intake("### What should be built?\n\n_No response_\n", 2.0, 10.0)


class Verdicts(unittest.TestCase):
    def test_model_verdict_field_is_ignored(self):
        doc = {"verdict": "clean", "findings": [{"severity": "blocking", "summary": "x"}]}
        clean, blocking, _ = b.derive_review(doc)
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)

    def test_a_blocking_finding_blocks_even_with_no_detail(self):
        clean, blocking, _ = b.derive_review({"findings": [{"severity": "blocking", "summary": "x"}]})
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)

    def test_findings_reach_the_coder_with_whatever_detail_they_carry(self):
        raw = {"file": "backend/src/app.ts", "line": "12", "repro": "curl -i /x", "suggested_fix": "", "requirement": None}
        view = b.finding_view("reviewer", "no kill switch", "app.use(r)", raw)
        self.assertEqual(view["file"], "backend/src/app.ts")
        self.assertNotIn("suggested_fix", view)
        text = b.describe_finding(view)
        self.assertIn("Where: backend/src/app.ts:12", text)
        self.assertIn("Repro: curl -i /x", text)
        self.assertEqual(b.describe_finding(b.finding_view("tester", "a: b", "", {})), "- [tester] a: b")

    def test_minor_only_is_clean(self):
        self.assertTrue(b.derive_review({"findings": [{"severity": "minor"}]})[0])

    def test_review_without_findings_list_is_invalid(self):
        with self.assertRaises(ValueError):
            b.derive_review({"verdict": "clean"})

    def test_a_flagless_test_needs_at_least_one_result(self):
        self.assertTrue(b.derive_test({"results": [{"flag": "", "passed": True}]}, [])[0])
        with self.assertRaises(ValueError):
            b.derive_test({"results": []}, [])

    def test_tester_passed_is_derived_and_flags_need_coverage(self):
        doc = {"passed": True, "results": [{"flag": "a", "check": "x", "passed": True}]}
        self.assertTrue(b.derive_test(doc, ["a"])[0])
        passed, failures = b.derive_test(doc, ["a", "b"])
        self.assertFalse(passed)
        self.assertEqual(failures[0]["flag"], "b")

    def test_tester_one_failure_fails(self):
        doc = {"passed": True, "results": [{"flag": "a", "passed": True}, {"flag": "a", "passed": False}]}
        self.assertFalse(b.derive_test(doc, ["a"])[0])

    def test_empty_results_with_flags_fails(self):
        self.assertFalse(b.derive_test({"results": []}, ["a"])[0])


class Flags(unittest.TestCase):
    def test_new_slugs_only(self):
        base = '[{"slug":"a","description":"."}]'
        head = '[{"slug":"a","description":"."},{"slug":"b","description":"."}]'
        self.assertEqual(b.new_flag_slugs(base, head), ["b"])

    def test_missing_base_or_garbage(self):
        self.assertEqual(b.new_flag_slugs("", '[{"slug":"a"}]'), ["a"])
        self.assertEqual(b.new_flag_slugs("[]", "not json"), [])

    def test_slug_pattern(self):
        for ok in ("todos-crud", "a1"):
            self.assertTrue(b.SLUG_RE.fullmatch(ok))
        for bad in ("../x", "A", "a b", "", "-a", "a/b"):
            self.assertFalse(b.SLUG_RE.fullmatch(bad))


class Guards(unittest.TestCase):
    def test_protected_paths(self):
        bad = b.protected_violations([".github/workflows/deploy-fly.yml", "fly.toml", "fly/provision.sh",
                                      "backend/src/feature-flags.ts", "INTAKE.md", "backend/src/app.ts",
                                      "flags.json", "backend/src/routes/notes.ts"])
        self.assertEqual(len(bad), 5)
        self.assertNotIn("flags.json", bad)

    def test_release_gate_needs_all_four_on_the_same_sha(self):
        self.assertTrue(b.release_gate(True, True, True, True, "abc", "abc"))
        for i in range(4):
            args = [True] * 4
            args[i] = False
            self.assertFalse(b.release_gate(*args, "abc", "abc"))
        self.assertFalse(b.release_gate(True, True, True, True, "abc", "def"))

    def test_render_replaces_and_rejects_leftovers(self):
        self.assertEqual(b.render("hi {{a}} {{a}}", {"a": 1}), "hi 1 1")
        with self.assertRaises(ValueError):
            b.render("hi {{a}} {{b}}", {"a": 1})


class Prompts(unittest.TestCase):
    """Every role prompt's placeholders are exactly the ones the orchestrator supplies."""
    SUPPLIED = {
        "coder": {"app_name", "round", "task", "findings_path", "build_kind"},
        "reviewer": {"app_name", "base_sha", "head_sha", "verdict_path", "rubric", "build_kind", "spec"},
        "reviewer-fast": {"app_name", "base_sha", "head_sha", "rubric", "build_kind"},
        "tester": {"app_name", "app_url", "head_sha", "report_path", "previous_report", "build_kind", "spec"},
        "planner": {"app_name", "build_kind", "task", "plan_path", "spec"},
        "pipeline": {"app_name", "head_sha", "failure_run_url", "diagnosis_path", "context_dir"},
        "postmortem": {"facts_path", "result_path", "categories"},
    }

    def test_placeholders(self):
        import re
        for role, supplied in self.SUPPLIED.items():
            text = (b.FACTORY_DIR / "agents" / "prompts" / f"{role}.md").read_text()
            self.assertEqual(set(re.findall(r"\{\{(\w+)\}\}", text)) - supplied, set(), role)


class SingleCallReview(unittest.TestCase):
    FILES = {"INTAKE.md": "Build notes.", "flags.json": '[{"slug": "notes-delete"}, {"slug": "unused"}]',
             "backend/src/app.ts": "app", "backend/src/feature-flags.ts": "flags", "backend/src/routes/notes.ts": "a\nb"}

    def git(self, *args):
        if args[0] == "diff" and "--name-only" in args:
            return "backend/src/routes/notes.ts\npackage-lock.json\n"
        if args[0] == "diff":
            return "DIFF TEXT"
        if args[0] == "show":
            return self.FILES.get(args[1].split(":", 1)[1], "")
        if args[0] == "grep":
            return "abc123:backend/src/routes/notes.ts:3:isFeatureEnabled(res, \"notes-delete\")\n" if "notes-delete" in args[3] else ""
        return ""

    def test_context_holds_the_spec_diff_numbered_files_and_flag_usage(self):
        ctx = b.build_review_context(self.git, "base1234", "abc12345", 10000)
        for needle in ("Build notes.", "DIFF TEXT", "1: a\n2: b", "# File at abc12345: backend/src/app.ts",
                       "# File at abc12345: backend/src/feature-flags.ts",
                       "- notes-delete: ", "- unused: NOT USED ANYWHERE"):
            self.assertIn(needle, ctx)
        self.assertNotIn("package-lock.json", ctx.split("# Where each")[0].replace("DIFF TEXT", ""))

    def test_a_change_too_big_for_one_prompt_is_refused_not_truncated(self):
        with self.assertRaises(b.ContextTooLarge):
            b.build_review_context(self.git, "base1234", "abc12345", 50)

    def test_call_retries_overload_then_returns_the_document(self):
        replies = [(429, "busy"), (200, {"choices": [{"message": {"content": '{"analysis": "a", "findings": [], "verdict": "clean"}'}}],
                                         "usage": {"prompt_tokens": 5}})]
        orig, orig_sleep = b.http, b.time.sleep
        b.http, b.time.sleep = (lambda *a, **k: replies.pop(0)), (lambda s: None)
        try:
            doc, usage = b.single_call_review("u", "k", "m", "sys", "user")
        finally:
            b.http, b.time.sleep = orig, orig_sleep
        self.assertEqual(doc["verdict"], "clean")
        self.assertEqual(usage["prompt_tokens"], 5)

    def test_unusable_replies_end_in_a_failure_the_caller_can_fall_back_on(self):
        orig, orig_sleep = b.http, b.time.sleep
        b.http, b.time.sleep = (lambda *a, **k: (200, {"choices": [{"message": {"content": "not json"}}]})), (lambda s: None)
        try:
            with self.assertRaises(b.FastReviewFailed):
                b.single_call_review("u", "k", "m", "sys", "user", attempts=2)
        finally:
            b.http, b.time.sleep = orig, orig_sleep


class PreviewToken(unittest.TestCase):
    def test_matches_the_shell_script_that_app_staging_uses(self):
        shell = subprocess.run([str(b.FACTORY_DIR / "infra/app-staging/preview-token.sh"), "demo-app"],
                               env={**os.environ, "PREVIEW_MASTER_SECRET": "x"}, capture_output=True, text=True)
        self.assertEqual(shell.stdout.strip(), b.preview_token("x", "demo-app"))


class TokenUsage(unittest.TestCase):
    STATE = {"stats": {"usage_to_metrics": {
        "agent": {"token_usages": [
            {"prompt_tokens": 13490, "completion_tokens": 144, "cache_read_tokens": 0},
            {"prompt_tokens": 60000, "completion_tokens": 65, "cache_read_tokens": 13616},
            {"prompt_tokens": 41000, "completion_tokens": 10, "cache_read_tokens": 0}]},
        "condenser": {"token_usages": [{"prompt_tokens": 70000}]}}}}

    def test_peak_is_the_largest_single_call_context(self):
        u = b.summarize_token_usage(self.STATE)
        self.assertEqual((u["calls"], u["condenser_calls"], u["peak_context"], u["last_context"]), (3, 1, 60000, 41000))
        self.assertEqual(u["prompt_tokens"], 114490)

    def test_missing_stats_is_zeroes_not_an_error(self):
        self.assertEqual(b.summarize_token_usage({})["peak_context"], 0)

    def test_merge_keeps_the_larger_peak_and_sums_the_rest(self):
        a = b.summarize_token_usage(self.STATE)
        m = b.merge_usage(a, b.summarize_token_usage({"stats": {"usage_to_metrics": {"agent": {"token_usages": [
            {"prompt_tokens": 90000, "completion_tokens": 1}]}}}}))
        self.assertEqual((m["calls"], m["peak_context"], m["last_context"]), (4, 90000, 90000))
        self.assertIsNone(b.merge_usage(None, None))


class SummaryRendering(unittest.TestCase):
    def test_summary_shows_usage_per_stage_and_the_run_peak(self):
        usage = lambda peak: {"calls": 3, "condenser_calls": 1, "peak_context": peak, "last_context": peak,
                              "prompt_tokens": 90000, "completion_tokens": 500, "cache_read_tokens": 80000,
                              "seconds": 125.4, "llm_seconds": 40.2}
        d = {"app": "x", "outcome": "released", "message": "ok", "cap_usd": 2.0, "spent_usd": 0.5, "review_passes": 1,
             "head_sha": "abc", "release": {"released": ["x.feature.a"]}, "blocking": [], "context_goal_tokens": 100000,
             "stages": [{"stage": "Coder", "agent": "coder", "round": "1", "cost_usd": 0.1, "verdict": "pushed", "usage": usage(54000)},
                        {"stage": "Review", "agent": "reviewer", "round": 1, "cost_usd": 0.1, "verdict": "clean", "usage": usage(120000)},
                        {"stage": "Release", "agent": "-", "round": "-", "cost_usd": 0, "verdict": "1 flag(s) released", "usage": None}]}
        out = b.render_summary(d)
        self.assertIn("| 125s (40s) | 3 | 54,000 | 90,000 (80,000) | 500 | 1 |", out)
        self.assertIn("120,000 :warning:", out)
        self.assertIn("Peak context this run**: 120,000 tokens (reviewer 1), over the goal of 100,000", out)


class WaitForDeploy(unittest.TestCase):
    def make(self, runs, skipped_ids):
        from unittest import mock
        run = object.__new__(b.BuildRun)
        run.app_repo, run.lim = "o/app", {"pipeline_timeout_minutes": 1}
        run.check_limits = lambda: None
        run.gh = lambda args, check=True: mock.Mock(stdout=json.dumps(runs))
        run.deploy_skipped = lambda rid: rid in skipped_ids
        return run

    def test_a_skipped_deploy_run_is_not_the_deploy(self):
        from unittest import mock
        done = lambda i, sha="s": {"databaseId": i, "headSha": sha, "status": "completed", "conclusion": "success", "url": ""}
        run = self.make([done(1), {**done(2), "status": "in_progress", "conclusion": ""}], {1})
        with mock.patch.object(b.time, "sleep", side_effect=RuntimeError("kept waiting")):
            with self.assertRaises(RuntimeError):
                run.wait_run("deploy-fly.yml", "s")
        self.assertEqual(self.make([done(1), done(2)], {1}).wait_run("deploy-fly.yml", "s")["databaseId"], 2)

    def test_other_workflows_are_not_filtered(self):
        done = {"databaseId": 1, "headSha": "s", "status": "completed", "conclusion": "success", "url": ""}
        self.assertEqual(self.make([done], {1}).wait_run("build.yml", "s")["databaseId"], 1)


class PreviousReport(unittest.TestCase):
    def test_round_one_has_none_and_later_rounds_point_at_the_last_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("none", str(b.previous_report(tmp, 1)))
            self.assertIn("none", str(b.previous_report(tmp, 2)))  # no file yet
            (Path(tmp) / "test-report-1.json").write_text("{}")
            self.assertEqual(b.previous_report(tmp, 2), Path(tmp) / "test-report-1.json")


class InstallDependencies(unittest.TestCase):
    def run_in(self, tmp, with_lock):
        run = object.__new__(b.BuildRun)
        run.app_dir = Path(tmp)
        if with_lock:
            (Path(tmp) / "package-lock.json").write_text("{}")
        return run

    def test_no_lockfile_means_no_install(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(b, "sh") as sh:
            self.run_in(tmp, False).install_dependencies()
            sh.assert_not_called()

    def test_install_runs_without_the_runners_secrets_and_a_failure_is_not_fatal(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(b, "sh") as sh, \
                mock.patch.dict(b.os.environ, {"FLY_API_TOKEN": "secret", "PATH": "/bin"}):
            sh.return_value.returncode = 1
            self.run_in(tmp, True).install_dependencies()
            env = sh.call_args.kwargs["env"]
            self.assertNotIn("FLY_API_TOKEN", env)
            self.assertEqual(sh.call_args.args[0][:2], ["npm", "ci"])


class CoderModelPerRound(unittest.TestCase):
    def run_for(self, profile):
        run = object.__new__(b.BuildRun)
        run.cfg = {"roles": {"coder": profile, "tester": {"model": "t"}}}
        return run

    def test_every_attempt_uses_model_unless_fix_model_is_set(self):
        run = self.run_for({"model": "fast"})
        self.assertEqual([run.model_for("coder", l) for l in ("1", "2", "fix1")], ["fast"] * 3)

    def test_fix_model_takes_over_after_round_one_for_the_coder_only(self):
        run = self.run_for({"model": "fast", "fix_model": "big"})
        self.assertEqual([run.model_for("coder", l) for l in ("1", "2", "fix1")], ["fast", "big", "big"])
        self.assertEqual(run.model_for("tester", "t2"), "t")


class ParallelReviewAndTest(unittest.TestCase):
    """The reviewer and the tester run at the same time. Agents are stubbed; git is faked."""

    def make(self, head_flags, agent):
        run = object.__new__(b.BuildRun)
        run.app, run.preview = "demo", "tok"
        run.cfg = {"roles": {"reviewer": {"mode": "agent"}}}
        run.work = Path("/tmp/work-test")
        run.state = b.State("/tmp/work-test/state.json", "demo", "1", "url")
        run.state.save = lambda: None
        shown = {"base": "[]", "head": head_flags}

        class R:  # stands in for subprocess.CompletedProcess
            def __init__(self, out): self.stdout, self.returncode = out, 0

        def git(*args, check=True, cwd=None):
            if args[0] == "show":
                return R(shown["base" if args[1].startswith("base") else "head"])
            return R("")
        run.git, run.restore_tree, run.agent_json = git, lambda cwd=None: None, agent
        return run

    CLEAN = {"analysis": "x", "findings": [], "verdict": "clean"}
    PASS = {"passed": True, "results": [{"flag": "f", "check": "c", "passed": True, "evidence": "e"}]}

    def test_reviewer_and_tester_overlap_and_split_the_budget(self):
        both_running = threading.Barrier(2, timeout=5)  # only passes if both are in flight together
        shares = {}

        def agent(role, label, values, path, *a, share=1.0, **k):
            shares[role] = share
            both_running.wait()
            return (self.CLEAN if role == "reviewer" else self.PASS), 0.1, None

        run = self.make('[{"slug": "f", "description": "d"}]', agent)
        clean, tpassed, flags, _ = run.review_and_test("base1", "head1", 1)
        self.assertTrue(clean and tpassed)
        self.assertEqual(flags, ["f"])
        self.assertEqual(shares, {"reviewer": 0.5, "tester": 0.5})
        self.assertEqual([x["stage"] for x in run.state.d["stages"]], ["Review", "Test"])

    def test_with_no_flags_the_tester_still_runs_against_the_intake(self):
        seen = []

        def agent(role, label, values, path, *a, share=1.0, **k):
            seen.append(role)
            return (self.CLEAN if role == "reviewer" else {"passed": True, "results": [
                {"flag": "", "check": "requirement 1", "passed": True, "evidence": "e"}]}), 0.1, None

        run = self.make("[]", agent)
        clean, tpassed, flags, _ = run.review_and_test("base1", "head1", 1)
        self.assertEqual(sorted(seen), ["reviewer", "tester"])
        self.assertTrue(clean and tpassed)
        self.assertEqual(flags, [])

    def test_a_failing_tester_still_records_the_reviewer_and_then_raises(self):
        def agent(role, label, values, path, *a, share=1.0, **k):
            if role == "tester":
                raise b.NeedsHuman("other", "the tester produced no valid output file twice")
            return self.CLEAN, 0.1, None

        run = self.make('[{"slug": "f", "description": "d"}]', agent)
        with self.assertRaises(b.NeedsHuman):
            run.review_and_test("base1", "head1", 1)
        self.assertEqual([x["stage"] for x in run.state.d["stages"]], ["Review"])

    def test_the_reviewer_failing_raises_after_the_tester_finished(self):
        done = []

        def agent(role, label, values, path, *a, share=1.0, **k):
            if role == "reviewer":
                raise b.BudgetExhausted("cap")
            done.append(role)
            return self.PASS, 0.1, None

        run = self.make('[{"slug": "f", "description": "d"}]', agent)
        with self.assertRaises(b.BudgetExhausted):
            run.review_and_test("base1", "head1", 1)
        self.assertEqual(done, ["tester"])
        self.assertEqual([x["stage"] for x in run.state.d["stages"]], ["Test"])


class BudgetAccounting(unittest.TestCase):
    def setUp(self):
        self.calls, self.spend = [], {}
        self._orig = b.http

        def fake(method, url, token=None, body=None, timeout=60):
            self.calls.append((method, body))
            if method == "POST":
                jwt = f"jwt{len(self.calls)}"
                self.spend[jwt] = 0.0
                return 200, {"token": jwt}
            return 200, {"spending_current": self.spend[url.split("jwtoken=")[1]]}
        b.http = fake

    def tearDown(self):
        b.http = self._orig

    def test_each_jwt_is_single_model_and_limited_to_what_is_left(self):
        bud = b.Budget("admin", 2.0, 100)
        j1 = bud.mint("m1")
        self.spend[j1] = 0.75
        self.assertAlmostEqual(bud.refresh(j1), 0.75)
        bud.mint("m2")
        post = [c[1] for c in self.calls if c[0] == "POST"]
        self.assertEqual([p["models"] for p in post], [["m1"], ["m2"]])
        self.assertEqual([p["spending_limit"] for p in post], [2.0, 1.25])

    def test_a_share_splits_what_is_left_between_parallel_agents(self):
        bud = b.Budget("admin", 2.0, 100)
        bud.mint("m1", share=0.5)
        bud.mint("m2", share=0.5)
        post = [c[1] for c in self.calls if c[0] == "POST"]
        self.assertEqual([p["spending_limit"] for p in post], [1.0, 1.0])

    def test_spend_sums_across_jwts_and_exhaustion_stops_minting(self):
        bud = b.Budget("admin", 1.0, 100)
        j1 = bud.mint("m1")
        self.spend[j1] = 0.6
        bud.refresh(j1)
        j2 = bud.mint("m2")
        self.spend[j2] = 0.45  # the crossing call completes, so overshoot is allowed
        self.assertAlmostEqual(bud.refresh(j2), 1.05)
        with self.assertRaises(b.BudgetExhausted):
            bud.mint("m1")


class VerificationStates(unittest.TestCase):
    def test_only_a_passed_check_passes(self):
        for state in ("failed", "blocked", "not_run"):
            doc = {"results": [{"flag": "a", "check": "x", "status": state}]}
            self.assertFalse(b.derive_test(doc, ["a"])[0], state)
        self.assertTrue(b.derive_test({"results": [{"flag": "a", "check": "x", "status": "passed"}]}, ["a"])[0])

    def test_status_wins_over_a_contradicting_boolean(self):
        doc = {"results": [{"flag": "a", "status": "blocked", "passed": True}]}
        self.assertFalse(b.derive_test(doc, ["a"])[0])

    def test_the_older_boolean_report_still_works_and_garbage_fails(self):
        self.assertEqual(b.check_state({"passed": True}), "passed")
        self.assertEqual(b.check_state({"passed": False}), "failed")
        self.assertEqual(b.check_state({"status": "great"}), "failed")
        self.assertEqual(b.check_state("passed"), "failed")

    def test_a_flag_with_no_result_is_not_run(self):
        record = b.verification_record({"results": [{"flag": "a", "check": "x", "status": "passed"}]}, ["a", "b"])
        self.assertEqual(record["counts"], {"passed": 1, "failed": 0, "blocked": 0, "not_run": 1})
        self.assertEqual(record["checks"][-1], {"flag": "b", "check": "coverage", "status": "not_run"})

    def test_limitations_are_kept_and_blank_ones_dropped(self):
        doc = {"results": [], "limitations": ["could not delete note 4", " ", "no browser"]}
        self.assertEqual(b.verification_record(doc, [])["limitations"], ["could not delete note 4", "no browser"])
        self.assertEqual(b.verification_record({"results": []}, [])["limitations"], [])

    def test_summary_shows_verification_limitations_and_scoreboard(self):
        d = {"app": "x", "outcome": "stuck", "message": "m", "cap_usd": 2.0, "spent_usd": 0.5, "review_passes": 2,
             "head_sha": "abc", "release": None, "blocking": [], "stages": [],
             "verification": {"round": 2, "sha": "abcdef123", "limitations": ["note 4 left behind"],
                              "counts": {"passed": 3, "failed": 1, "blocked": 1, "not_run": 0}, "checks": []},
             "scoreboard": [{"round": 1, "counts": {"passed": 2, "failed": 2, "blocked": 1, "not_run": 0}, "blocking": ["a"]},
                            {"round": 2, "counts": {"passed": 3, "failed": 1, "blocked": 1, "not_run": 0}, "blocking": []}]}
        out = b.render_summary(d)
        self.assertIn("3 passed, 1 failed, 1 blocked, 0 not run", out)
        self.assertIn("- note 4 left behind", out)
        self.assertIn("- round 1: 2 / 2 / 1 / 0, 1 open", out)
        self.assertNotIn("Verification", b.render_summary({**d, "verification": None, "scoreboard": []}))


class Scoreboard(unittest.TestCase):
    def entry(self, rnd, checks, blocking=()):
        record = {"counts": {s: 0 for s in b.CHECK_STATES},
                  "checks": [{"flag": "a", "check": c, "status": st} for c, st in checks.items()]}
        return b.scoreboard_entry(rnd, "sha", record, [{"summary": x} for x in blocking])

    def test_entry_keys_checks_by_flag_and_normalises_findings(self):
        e = self.entry(1, {"x": "failed"}, ["  Missing   Flag "])
        self.assertEqual(e["checks"], {"a: x": "failed"})
        self.assertEqual(e["blocking"], ["missing flag"])

    def test_identical_open_items_for_n_rounds_is_stalled(self):
        same = [self.entry(i, {"x": "failed", "y": "passed"}, ["no kill switch"]) for i in (1, 2, 3)]
        self.assertTrue(b.stalled(same, 3))
        self.assertFalse(b.stalled(same[:2], 3))

    def test_any_change_between_rounds_is_progress(self):
        a, c = self.entry(1, {"x": "failed"}), self.entry(2, {"x": "passed"}, ["new finding"])
        self.assertFalse(b.stalled([a, a, c], 3))
        self.assertFalse(b.stalled([a, c, c], 3))

    def test_nothing_open_is_never_stalled_and_small_n_disables_it(self):
        clean = [self.entry(i, {"x": "passed"}) for i in (1, 2, 3)]
        self.assertFalse(b.stalled(clean, 3))
        failing = [self.entry(i, {"x": "failed"}) for i in (1, 2, 3)]
        self.assertFalse(b.stalled(failing, 0))
        self.assertFalse(b.stalled(failing, 1))


class Watchdog(unittest.TestCase):
    ok, bad = {"healthy": True, "errors": 0}, {"healthy": False, "errors": 0}

    def test_counts_only_error_level_json_lines(self):
        log = '{"level":"info"}\n{"level": "error","msg":"x"}\n{"level":"FATAL"}\nplain error text\n'
        self.assertEqual(b.count_errors(log), 2)
        self.assertEqual(b.count_errors(None), 0)

    def test_consecutive_health_failures_trip_it(self):
        self.assertIsNotNone(b.watchdog_trip([self.ok, self.bad, self.bad, self.bad], 0, 3, 5))

    def test_failures_that_recover_do_not(self):
        self.assertIsNone(b.watchdog_trip([self.bad, self.bad, self.ok, self.bad, self.bad], 0, 3, 5))

    def test_a_rise_in_errors_over_the_baseline_trips_it(self):
        self.assertIsNotNone(b.watchdog_trip([{"healthy": True, "errors": 9}], 3, 3, 5))
        self.assertIsNone(b.watchdog_trip([{"healthy": True, "errors": 7}], 3, 3, 5))

    def test_errors_that_were_already_there_do_not(self):
        self.assertIsNone(b.watchdog_trip([{"healthy": True, "errors": 40}] * 4, 40, 3, 5))

    def test_no_samples_no_trip(self):
        self.assertIsNone(b.watchdog_trip([], 0, 3, 5))

    def make(self, minutes, released):
        run = object.__new__(b.BuildRun)
        run.lim = {"watchdog_minutes": minutes, "watchdog_interval_seconds": 0, "watchdog_max_failures": 2, "watchdog_max_errors": 5}
        run.app, run.deadline = "x", float("inf")
        run.state = b.State("/tmp/unused-state.json", "x", "1", "u")
        run.state.save = lambda: None
        run.state.d["release"] = {"released": released, "kept": ["x.feature.old"]}
        run.app_error_count = lambda: 0
        return run

    def test_a_tripped_watchdog_switches_off_only_what_this_run_released(self):
        from unittest import mock
        run = self.make(0.05, ["x.feature.new"])
        run.disable_flags = mock.Mock(return_value=[])
        with mock.patch.object(b, "http", return_value=(500, {})), mock.patch.object(b.time, "sleep"):
            run.watch_release()
        run.disable_flags.assert_called_once_with(["x.feature.new"])
        self.assertEqual(run.state.d["outcome"], "watchdog_disabled")
        self.assertIn("health check failed", run.state.d["message"])

    def test_a_flag_that_will_not_turn_off_is_called_out(self):
        from unittest import mock
        run = self.make(0.05, ["x.feature.new"])
        run.disable_flags = mock.Mock(return_value=["x.feature.new"])
        with mock.patch.object(b, "http", return_value=(500, {})), mock.patch.object(b.time, "sleep"):
            run.watch_release()
        self.assertIn("turn them off in GrowthBook now", run.state.d["message"])

    def test_a_healthy_app_is_left_alone(self):
        from unittest import mock
        run = self.make(0.0005, ["x.feature.new"])
        run.disable_flags = mock.Mock()
        with mock.patch.object(b, "http", return_value=(200, {})), mock.patch.object(b.time, "sleep"):
            run.watch_release()
        run.disable_flags.assert_not_called()
        self.assertNotEqual(run.state.d["outcome"], "watchdog_disabled")

    def test_the_outcome_is_saved_before_the_watch_starts_so_a_cancel_cannot_look_like_a_crash(self):
        from unittest import mock
        run = self.make(5, ["x.feature.new"])
        saves = []
        run.state.save = lambda: saves.append(run.state.d["outcome"])
        run.state.d["outcome"] = "released"
        run.disable_flags = mock.Mock()
        with mock.patch.object(b, "http", side_effect=KeyboardInterrupt), mock.patch.object(b.time, "sleep"):
            with self.assertRaises(KeyboardInterrupt):
                run.watch_release()
        self.assertEqual(saves[:1], ["released"])

    def test_zero_minutes_or_nothing_released_skips_the_watch(self):
        from unittest import mock
        for minutes, released in ((0, ["x.feature.new"]), (5, [])):
            run = self.make(minutes, released)
            run.disable_flags = mock.Mock()
            with mock.patch.object(b, "http") as http:
                run.watch_release()
            http.assert_not_called()


class SpendLedger(unittest.TestCase):
    def test_line_round_trips_and_only_todays_lines_count(self):
        line = b.ledger_line("2026-10-10", "notes", 0.5, "42")
        self.assertEqual(line, "ledger 2026-10-10 notes 0.5000 run:42")
        comments = [line, b.ledger_line("2026-10-10", "todo", 1.25, "43"), b.ledger_line("2026-10-09", "todo", 9.0, "40"),
                    "a human comment", "ledger 2026-10-10 notes lots run:44", ""]
        self.assertEqual(b.ledger_total(comments, "2026-10-10"), 1.75)

    def test_a_run_id_seen_twice_counts_once(self):
        line = b.ledger_line("2026-10-10", "notes", 0.5, "42")
        self.assertEqual(b.ledger_total([line, line], "2026-10-10"), 0.5)

    def make(self, cap, comments, issue=7):
        from unittest import mock
        run = object.__new__(b.BuildRun)
        run.lim, run.factory_repo, run.factory_token = {"daily_cost_cap_usd": cap}, "o/f", "t"
        run.state = b.State("/tmp/unused-state.json", "x", "1", "u")
        run.ledger_issue = lambda: issue
        run.gh = mock.Mock(return_value=mock.Mock(stdout="\n".join(comments)))
        return run

    def today_line(self, usd, run_id):
        return b.ledger_line(b.time.strftime("%Y-%m-%d", b.time.gmtime()), "a", usd, run_id)

    def test_the_cap_stops_a_new_run_and_records_what_was_spent(self):
        run = self.make(5.0, [self.today_line(3.0, "1"), self.today_line(2.5, "2")])
        with self.assertRaises(b.NeedsHuman) as cm:
            run.check_daily_cap()
        self.assertIn("$5.50", str(cm.exception))
        self.assertEqual(run.state.d["daily_spent_usd"], 5.5)

    def test_under_the_cap_zero_cap_and_no_ledger_yet_all_let_it_run(self):
        self.make(5.0, [self.today_line(3.0, "1")]).check_daily_cap()
        run = self.make(0, [self.today_line(99.0, "1")])
        run.check_daily_cap()
        run.gh.assert_not_called()
        self.make(5.0, [], issue=None).check_daily_cap()


class JsonOutput(unittest.TestCase):
    def write(self, text):
        import tempfile
        f = Path(tempfile.mkdtemp()) / "out.json"
        if text is not None:
            f.write_text(text)
        return f

    def test_the_problem_is_described_for_the_agent(self):
        self.assertIn("was not written", b.json_problem(self.write(None)))
        self.assertIn("is empty", b.json_problem(self.write("  \n")))
        # What the tester wrote in the first real watchdog test: unescaped quotes inside a string.
        bad = b.json_problem(self.write('{"evidence": "Response: {"intervalSeconds":2}"}'))
        self.assertIn("not valid JSON", bad)
        self.assertIn("line 1 column", bad)
        self.assertIn("not escaped", bad)

    def test_a_usable_file_has_no_problem_and_a_rejected_one_says_why(self):
        self.assertIsNone(b.json_problem(self.write('{"a": 1}')))
        def check(doc):
            raise ValueError("no results list")
        self.assertIn("no results list", b.json_problem(self.write('{"a": 1}'), check))
        self.assertIn("not accepted", b.json_problem(self.write('{"a": 1}'), lambda d: False))

    def test_the_second_attempt_is_told_what_was_wrong_with_the_first(self):
        from unittest import mock
        run = object.__new__(b.BuildRun)
        path = self.write(None)
        notes, attempts = [], []

        def invoke(role, label, values, extra_env, cwd, home, share, note=None):
            attempts.append(label)
            notes.append(note)
            path.write_text('{"results": [' if len(attempts) == 1 else '{"results": []}')
            return 0, 0.1, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        doc, cost, _ = run.agent_json("tester", "t1", {}, path)
        self.assertEqual(doc, {"results": []})
        self.assertEqual((attempts, notes[0]), (["t1", "t1b"], None))
        self.assertIn("not valid JSON", notes[1])
        self.assertAlmostEqual(cost, 0.2)

    def test_two_bad_attempts_end_in_needs_human_with_the_last_reason(self):
        run = object.__new__(b.BuildRun)
        path = self.write(None)

        def invoke(role, label, values, extra_env, cwd, home, share, note=None):
            path.write_text("{oops")
            return 0, 0.1, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        with self.assertRaises(b.NeedsHuman) as cm:
            run.agent_json("tester", "t1", {}, path)
        self.assertIn("no valid output file twice", str(cm.exception))
        self.assertIn("last problem: it is not valid JSON", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
