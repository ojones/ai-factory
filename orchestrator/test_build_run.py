"""Unit tests for the Build Run's deterministic logic. Run: python3 -m unittest discover orchestrator"""
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
        "reviewer": {"app_name", "base_sha", "head_sha", "verdict_path", "rubric", "build_kind"},
        "reviewer-fast": {"app_name", "base_sha", "head_sha", "rubric", "build_kind"},
        "tester": {"app_name", "app_url", "head_sha", "report_path", "build_kind"},
        "pipeline": {"app_name", "head_sha", "failure_run_url", "diagnosis_path", "context_dir"},
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
                              "prompt_tokens": 90000, "completion_tokens": 500, "cache_read_tokens": 80000}
        d = {"app": "x", "outcome": "released", "message": "ok", "cap_usd": 2.0, "spent_usd": 0.5, "review_passes": 1,
             "head_sha": "abc", "release": {"released": ["x.feature.a"]}, "blocking": [], "context_goal_tokens": 100000,
             "stages": [{"stage": "Coder", "agent": "coder", "round": "1", "cost_usd": 0.1, "verdict": "pushed", "usage": usage(54000)},
                        {"stage": "Review", "agent": "reviewer", "round": 1, "cost_usd": 0.1, "verdict": "clean", "usage": usage(120000)},
                        {"stage": "Release", "agent": "-", "round": "-", "cost_usd": 0, "verdict": "1 flag(s) released", "usage": None}]}
        out = b.render_summary(d)
        self.assertIn("| 3 | 54,000 | 90,000 (80,000) | 500 | 1 |", out)
        self.assertIn("120,000 :warning:", out)
        self.assertIn("Peak context this run**: 120,000 tokens (reviewer 1), over the goal of 100,000", out)


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


if __name__ == "__main__":
    unittest.main()
