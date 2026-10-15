"""Unit tests for the Build Run's deterministic logic. Run: python3 -m unittest discover orchestrator"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

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


def finding(**over):
    """A reviewer finding as the schema requires it: blocking, backed by a cited file and line."""
    return {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "x", "evidence": "e",
            "file": "backend/src/a.ts", "line": "3", "requirement": "", "suggested_fix": "", "repro": "", **over}


class Verdicts(unittest.TestCase):
    def test_model_verdict_field_is_ignored(self):
        clean, blocking, _ = b.derive_review({"verdict": "clean", "findings": [finding()]})
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)

    def test_a_backed_blocking_finding_blocks(self):
        for f in (finding(), finding(category="security", evidence_kind="repro", file="", line="", repro="curl -i /x"),
                  finding(category="requirement_not_met"), finding(category="flag_misuse"), finding(category="data_safety"), finding(category="test_quality")):
            clean, blocking, _ = b.derive_review({"findings": [f]})
            self.assertEqual((clean, len(blocking)), (False, 1), f["category"])

    def test_a_blocking_finding_the_fields_do_not_back_is_minor_with_the_reason(self):
        for f, why in ((finding(evidence_kind="opinion"), "evidence `opinion`"),
                       (finding(file="", line=""), "not backed by a file and line"),
                       (finding(line=""), "not backed by a file and line"),
                       (finding(evidence_kind="repro", repro=""), "not backed by a repro"),
                       (finding(category="style"), "category `style` cannot block"),
                       (finding(category="duplication"), "cannot block"), (finding(category="other"), "cannot block")):
            clean, blocking, minor = b.derive_review({"findings": [f]})
            self.assertEqual((clean, blocking), (True, []), why)
            self.assertEqual(minor[0]["severity"], "minor")
            self.assertIn(why, minor[0]["downgraded"])

    def test_a_minor_finding_is_never_raised_whatever_its_fields(self):
        clean, blocking, minor = b.derive_review({"findings": [finding(severity="minor", category="security")]})
        self.assertEqual((clean, blocking, len(minor)), (True, [], 1))
        self.assertNotIn("downgraded", minor[0])

    def test_findings_without_the_structure_are_refused_so_the_reviewer_is_asked_again(self):
        bad = finding()
        del bad["category"]
        for f in (bad, finding(category="nonsense"), finding(evidence_kind="vibes")):
            with self.assertRaises(ValueError):
                b.derive_review({"findings": [f]})

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
        self.assertTrue(b.derive_review({"findings": [finding(severity="minor")]})[0])

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
        "coder": {"app_name", "round", "task", "findings_path", "build_kind", "issue_ref"},
        "reviewer": {"app_name", "base_sha", "head_sha", "verdict_path", "rubric", "build_kind", "spec"},
        "reviewer-fast": {"app_name", "base_sha", "head_sha", "rubric", "build_kind"},
        "tester": {"app_name", "app_url", "head_sha", "report_path", "previous_report", "build_kind", "spec", "api_check", "ui_section"},
        "planner": {"app_name", "build_kind", "task", "plan_path", "spec"},
        "pipeline": {"app_name", "head_sha", "failure_run_url", "diagnosis_path", "context_dir"},
        "retrospective": {"facts_path", "result_path", "categories"},
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


class ReviewBeforePushThenTest(unittest.TestCase):
    """The reviewer reads the local commit before the push; the tester drives the deployed app after it. Agents are stubbed; git is faked."""

    def make(self, head_flags, agent):
        run = object.__new__(b.BuildRun)
        run.app, run.preview = "demo", "tok"
        run.cfg = {"roles": {"reviewer": {"mode": "agent"}}}
        run.lim = {}
        run.reuse_flags = []
        run.work = Path(__import__("tempfile").mkdtemp(prefix="work-test-"))
        run.state = b.State(run.work / "state.json", "demo", "1", "url")
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

    CLEAN = {"analysis": "x", "findings": [], "improvements": [], "verdict": "clean"}
    PASS = {"passed": True, "results": [{"flag": "f", "check": "c", "passed": True, "evidence": "e"}]}
    FLAGS = '[{"slug": "f", "description": "d"}]'

    def test_the_reviewer_runs_alone_and_before_anything_is_pushed(self):
        roles = []

        def agent(role, label, values, path, *a, **k):
            roles.append(role)
            return self.CLEAN, 0.1, None

        run = self.make(self.FLAGS, agent)
        clean, blocking, minor = run.review_before_push("base1", "head1", 1)
        self.assertEqual((clean, blocking), (True, []))
        self.assertEqual({m["source"] for m in minor}, {"orchestrator"})  # the flag in this change has no use and no issue reference
        self.assertEqual(roles, ["reviewer"])  # no tester, no deploy: nothing is live yet
        self.assertEqual(run.run_flags("base1", "head1"), ["f"])
        self.assertEqual([x["stage"] for x in run.state.d["stages"]], ["Review"])

    def test_a_blocking_finding_is_returned_so_the_coder_can_fix_it_before_the_push(self):
        doc = dict(self.CLEAN, verdict="clean", findings=[finding(summary="injection", category="security")])
        run = self.make(self.FLAGS, lambda *a, **k: (doc, 0.1, None))
        clean, blocking, _ = run.review_before_push("base1", "head1", 1)
        self.assertFalse(clean)  # the model's own "clean" verdict is ignored
        self.assertEqual(len(blocking), 1)

    def test_mechanical_flag_findings_come_from_the_orchestrator_and_are_always_minor(self):
        shown = {"flags.json": json.dumps([{"slug": "used", "description": "o/r#4: used"}, {"slug": "idle", "description": "o/r#5: never read"},
                                           {"slug": "bare", "description": "no reference"}, {"slug": "old", "description": "x"}])}

        def git(*args):
            if args[0] == "show":
                return shown[args[1].split(":", 1)[1]]
            hits = {'"used"': "head:backend/src/routes/n.ts:9:  if (isFeatureEnabled(res, 'used'))", '"bare"': "head:backend/src/n.ts:2:x('bare')\nhead:backend/src/n.test.ts:4:'bare'"}
            return "\n".join(v for k, v in hits.items() if k in args)
        found = b.flag_findings(git, "head", ["used", "idle", "bare", "gone"])
        self.assertEqual([(f["summary"].split("`")[1], "no code outside the tests" in f["summary"]) for f in found],
                         [("idle", True), ("bare", False)])
        self.assertTrue(all(f["severity"] == "minor" and f["category"] == "flag_misuse" and f["source"] == "orchestrator" for f in found))
        self.assertEqual(b.flag_findings(lambda *a: "not json", "head", ["used"]), [])  # an unreadable manifest is not a finding

    def test_a_flag_read_only_by_a_test_counts_as_unused(self):
        git = lambda *a: json.dumps([{"slug": "t", "description": "o/r#1: x"}]) if a[0] == "show" else "head:backend/src/x.test.ts:3:'t'"
        self.assertIn("no code outside the tests", b.flag_findings(git, "head", ["t"])[0]["summary"])

    def test_the_tester_runs_after_the_push_and_says_what_a_failure_means(self):
        run = self.make(self.FLAGS, lambda role, *a, **k: (self.PASS, 0.1, None))
        self.assertEqual(run.test_deployed("base1", "head1", 1, ["f"])[::2], (True, "ok"))
        self.assertEqual([x["stage"] for x in run.state.d["stages"]], ["Test"])

    def test_with_no_flags_the_tester_still_runs_against_the_intake(self):
        seen = []

        def agent(role, label, values, path, *a, **k):
            seen.append(role)
            return {"passed": True, "results": [{"flag": "", "check": "requirement 1", "passed": True, "evidence": "e"}]}, 0.1, None

        run = self.make("[]", agent)
        passed, failures, impact = run.test_deployed("base1", "head1", 1, run.run_flags("base1", "head1"))
        self.assertEqual((seen, passed, failures, impact), (["tester"], True, [], "ok"))

    def test_a_failure_of_the_new_change_is_dark_only_and_one_of_released_behaviour_is_a_regression(self):
        broken_new = {"flag": "f", "check": "new route", "status": "failed", "evidence": "e", "scope": "new", "api": ["a1"]}
        broken_old = {"flag": "", "check": "GET /api/notes", "status": "failed", "evidence": "e", "scope": "existing", "api": ["a2"]}
        self.assertEqual(b.test_impact([]), "ok")
        self.assertEqual(b.test_impact([broken_new]), "dark_only")
        self.assertEqual(b.test_impact([broken_new, broken_old]), "regression")
        # the model's word alone is not enough: no helper observation, no regression; and blocked or not_run is not "broken"
        self.assertEqual(b.test_impact([dict(broken_old, api=[])]), "dark_only")
        self.assertEqual(b.test_impact([dict(broken_old, status="blocked")]), "dark_only")
        self.assertEqual(b.test_impact([dict(broken_old, status="not_run")]), "dark_only")

    def test_a_failing_tester_with_nothing_seen_to_fail_raises_for_a_person(self):
        def agent(role, *a, **k):
            raise b.NeedsHuman("other", "the tester produced no valid output file twice")

        run = self.make(self.FLAGS, agent)
        with self.assertRaises(b.NeedsHuman):
            run.test_deployed("base1", "head1", 1, ["f"])

    def test_improvements_are_kept_deduplicated_and_only_the_known_kinds(self):
        doc = dict(self.CLEAN, improvements=[
            {"target": "factory", "summary": "The prompt never says  to trim input", "evidence": "e"},
            {"target": "factory", "summary": "the prompt never says to trim input", "evidence": "again"},
            {"target": "managed_app", "summary": "Add a test for empty text", "evidence": ""},
            {"target": "nobody", "summary": "ignored"}, {"target": "factory", "summary": "  "}, "junk"])
        run = self.make(self.FLAGS, lambda *a, **k: (doc, 0.1, None))
        run.review_before_push("base1", "head1", 1)
        run.note_improvements(doc, "reviewer")  # a second sighting adds nothing
        kept = run.state.d["improvements"]
        self.assertEqual([(i["source"], i["target"]) for i in kept], [("reviewer", "factory"), ("reviewer", "managed_app")])


class SuppressionsAndLintConfig(unittest.TestCase):
    DIFF = ("diff --git a/backend/src/a.ts b/backend/src/a.ts\n--- a/backend/src/a.ts\n+++ b/backend/src/a.ts\n@@ -3,0 +4,3 @@\n"
            "+const ok = 1;\n+// eslint-disable-next-line @typescript-eslint/no-explicit-any\n+const x: any = 2;\n"
            "diff --git a/frontend/src/b.tsx b/frontend/src/b.tsx\n--- a/frontend/src/b.tsx\n+++ b/frontend/src/b.tsx\n@@ -10 +10 @@\n"
            "-old\n+// @ts-ignore\n")

    def test_an_added_suppression_is_named_with_its_place_and_is_always_minor(self):
        found = b.suppression_findings(lambda *a: self.DIFF, "base", "head")
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f["severity"], f["source"], f["file"], f["line"]), ("minor", "orchestrator", "backend/src/a.ts", "5"))
        self.assertIn("2 lint or type-check suppression(s)", f["summary"])
        self.assertIn("frontend/src/b.tsx:10", f["evidence"])

    def test_no_suppression_means_no_finding(self):
        self.assertEqual(b.suppression_findings(lambda *a: "+++ b/a.ts\n@@ -1 +1 @@\n+const x = 1;\n", "base", "head"), [])
        self.assertEqual(b.suppression_findings(lambda *a: "", "base", "head"), [])

    def run_with_template(self, files, labels=("template-sync",)):
        """A real app checkout with a base commit, and a Starter Template folder holding `files`."""
        import subprocess
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
        run = object.__new__(b.BuildRun)
        run.app_dir, run.agent_user, run.auth_header = app, None, "x"
        return run, git, origin, tmp / "factory"

    def test_the_lint_config_is_staged_after_the_base_and_pushed_only_with_the_coders_work(self):
        from unittest import mock
        run, git, origin, factory = self.run_with_template({"eslint.config.mjs": "// new rules\n", ".github/workflows/test-gate.yml": "name: gate\n"})
        pushes = []
        real_sh = b.sh

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            if cmd[:2] == ["git", "push"]:
                pushes.append(cmd)
                return real_sh(["git", "push", "-q", "origin", "HEAD:main"], cwd=cwd, check=True)
            return real_sh(cmd, cwd=cwd, env=env, check=check, timeout=timeout)
        with mock.patch.object(b, "FACTORY_DIR", factory), mock.patch.object(b, "sh", fake_sh):
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
        with mock.patch.object(b, "FACTORY_DIR", factory):
            run.apply_template_files({"update-intake"})
            run.stage_template_config({"update-intake"})
        self.assertEqual((run.app_dir / "eslint.config.mjs").read_text(), "// old\n")


class RoundLoop(unittest.TestCase):
    """The order of a Build Run's rounds with every stage stubbed: review the local commit, push only a clean one, wait for the deploy,
    then test it."""

    def make(self, reviews, tests, pipeline_fix=False):
        run = object.__new__(b.BuildRun)
        run.app, run.build_kind, run.update_intake, run.plan_meta = "demo", "update", False, None
        run.task, run.retiring, run.reuse_flags, run.retry_state = "do it", (), [], {}
        run.lim = {"review_rounds": 3, "stuck_rounds": 0}
        run.work = Path(__import__("tempfile").mkdtemp(prefix="loop-test-"))
        run.art = run.work
        run.state = b.State(run.work / "state.json", "demo", "1", "url")
        run.state.d["base_sha"] = "base"
        run.calls, run.heads = [], iter(["c1", "c2", "c3", "c4"])
        run.setup = lambda: None
        run.coder = lambda label, task, path: (run.calls.append(f"coder{label}"), next(run.heads))[1]
        reviews, tests = iter(reviews), iter(tests)

        def review(base, head, rnd):
            run.calls.append(f"review {head}")
            return next(reviews)
        run.review_before_push = review
        run.run_flags = lambda base, head: ["f"]
        run.push = lambda head: (run.calls.append(f"push {head}"), run.state.d["commits"].append(head))
        fixes = iter([pipeline_fix])

        def pipeline(sha):
            run.calls.append(f"pipeline {sha}")
            if next(fixes, False):
                run.last = "fix1"  # the coder's fix is now HEAD
                raise b.PipelineFix("fix1")
            return sha
        run.pipeline = pipeline

        def test(base, head, rnd, flags):
            run.calls.append(f"test {head}")
            return next(tests)
        run.test_deployed = test
        run.head = lambda: run.last
        run.record_round = lambda *a: None
        run.release = lambda flags, head: run.calls.append("release")
        run.link_flags_to_issue = lambda flags: None
        run.watch_release = lambda: None
        run.archive_retired_flags = lambda base, head: None
        run.check_limits = lambda: None
        run.cap = 1.0
        return run

    def go(self, run):
        # the coder's last commit is what HEAD points at
        orig = run.coder
        run.coder = lambda *a: setattr(run, "last", orig(*a)) or run.last
        run.last = None
        run.run()

    CLEAN, BLOCKED = (True, [], []), (False, [{"summary": "bad", "evidence": "e"}], [])
    PASSED, FAILED_NEW = (True, [], "ok"), (False, [{"flag": "f", "check": "new", "status": "failed", "scope": "new"}], "dark_only")

    def test_a_second_failed_deployed_test_stops_the_run_before_a_third_round(self):
        run = self.make([self.CLEAN, self.CLEAN, self.CLEAN], [self.FAILED_NEW, self.FAILED_NEW, self.PASSED])
        run.lim["test_rounds"] = 2
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "round_limit")
        self.assertEqual(run.calls.count("coder2"), 1)
        self.assertNotIn("coder3", run.calls)

    def test_blocked_reviews_do_not_use_up_the_test_rounds(self):
        run = self.make([self.BLOCKED, self.BLOCKED, self.CLEAN], [self.PASSED])
        run.lim["test_rounds"] = 1
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "released")

    def test_a_clean_review_pushes_then_the_tester_runs_then_it_releases(self):
        run = self.make([self.CLEAN], [self.PASSED])
        self.go(run)
        self.assertEqual(run.calls, ["coder1", "review c1", "push c1", "pipeline c1", "test c1", "release"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_a_blocked_review_sends_the_code_back_to_the_coder_and_nothing_is_pushed(self):
        run = self.make([self.BLOCKED, self.CLEAN], [self.PASSED])
        self.go(run)
        self.assertEqual(run.calls[:4], ["coder1", "review c1", "coder2", "review c2"])
        self.assertNotIn("push c1", run.calls)  # the blocked commit never reached main
        self.assertEqual(run.state.d["commits"], ["c2"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_a_dark_failure_is_fixed_forward_in_the_next_round(self):
        run = self.make([self.CLEAN, self.CLEAN], [self.FAILED_NEW, self.PASSED])
        self.go(run)
        self.assertEqual(run.calls, ["coder1", "review c1", "push c1", "pipeline c1", "test c1", "coder2",
                                     "review c2", "push c2", "pipeline c2", "test c2", "release"])
        self.assertEqual(run.state.d["outcome"], "released")

    UNVERIFIED_BLOCKED = (False, [{"flag": "f", "check": "send mail", "status": "blocked", "scope": "new", "evidence": "app unreachable"}], "dark_only")
    UNVERIFIED_NOT_RUN = (False, [{"flag": "f", "check": "coverage", "status": "not_run", "scope": "new", "evidence": "no result"}], "dark_only")

    def test_checks_that_could_not_be_run_are_retested_not_sent_to_the_coder(self):
        run = self.make([self.CLEAN], [self.UNVERIFIED_BLOCKED, self.PASSED])
        self.go(run)
        self.assertEqual(run.calls, ["coder1", "review c1", "push c1", "pipeline c1", "test c1", "test c1", "release"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_checks_that_still_cannot_be_verified_stop_the_run_for_a_person_with_no_coder_round(self):
        run = self.make([self.CLEAN], [self.UNVERIFIED_BLOCKED, self.UNVERIFIED_NOT_RUN])
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "needs_human")
        self.assertIn("could not be verified", run.state.d["message"])
        self.assertIn("coverage", run.state.d["message"])
        self.assertEqual(run.calls.count("coder2"), 0)
        self.assertNotIn("release", run.calls)

    def test_with_retests_switched_off_the_first_unverified_pass_stops_the_run(self):
        run = self.make([self.CLEAN], [self.UNVERIFIED_BLOCKED])
        run.lim["test_retries"] = 0
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "needs_human")
        self.assertEqual(run.calls.count("test c1"), 1)

    def test_only_the_failed_checks_reach_the_coder_when_some_failed_and_some_were_blocked(self):
        failed = {"flag": "f", "check": "new route answers 201", "status": "failed", "scope": "new", "evidence": "got 500"}
        run = self.make([self.CLEAN, self.CLEAN], [(False, [failed, self.UNVERIFIED_BLOCKED[1][0]], "dark_only"), self.PASSED])
        tasks = []
        orig = run.coder
        run.coder = lambda label, task, path: (tasks.append(task), orig(label, task, path))[1]
        self.go(run)
        fix_list = next(t for t in tasks if "fix list" in t)
        self.assertIn("new route answers 201", fix_list)
        self.assertNotIn("send mail", fix_list)

    def test_a_regression_ends_the_run_at_once_so_finalize_can_roll_the_deploy_back(self):
        broken = {"flag": "", "check": "GET /api/notes", "status": "failed", "scope": "existing", "api": ["a"]}
        run = self.make([self.CLEAN], [(False, [broken], "regression")])
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "regression")
        self.assertNotIn("release", run.calls)
        self.assertEqual(run.calls.count("coder2"), 0)  # no more rounds on top of a regression

    def test_a_fix_the_pipeline_needed_is_reviewed_before_it_is_pushed(self):
        run = self.make([self.CLEAN, self.CLEAN], [self.PASSED], pipeline_fix=True)
        self.go(run)
        self.assertEqual(run.calls[:7], ["coder1", "review c1", "push c1", "pipeline c1", "review fix1", "push fix1", "pipeline fix1"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_rounds_that_never_pass_review_end_at_the_round_limit_with_nothing_pushed(self):
        run = self.make([self.BLOCKED] * 3, [])
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "round_limit")
        self.assertEqual(run.state.d["commits"], [])


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

    def test_a_check_whose_own_evidence_admits_it_was_not_observed_does_not_pass(self):
        # The first real run on an unobservable requirement: marked passed, evidence said it could not be seen.
        real = "Unable to directly observe logs in production, but feature flag mechanism is working correctly"
        self.assertEqual(b.check_state({"status": "passed", "evidence": real}), "not_run")
        self.assertFalse(b.derive_test({"results": [{"flag": "a", "check": "logs the hash", "status": "passed", "evidence": real}]}, ["a"])[0])
        for admission in ("Could not verify in production", "I cannot see the logs", "Not able to confirm", "no way to inspect it",
                          "This is unverifiable from outside", "not verified"):
            self.assertEqual(b.check_state({"status": "passed", "evidence": admission}), "not_run", admission)

    def test_ordinary_evidence_and_evidence_backed_by_a_test_run_still_pass(self):
        for ok in ('Status: 200, Response: {"intervalSeconds":2}', "Response body has no hash. Hash not visible in headers either.",
                   "Unable to observe the logs from outside, but the unit test 'logs the hash' passes (npm run test:file: 1 passed)",
                   "", None):
            self.assertEqual(b.check_state({"status": "passed", "evidence": ok}), "passed", ok)
        self.assertEqual(b.check_state({"status": "failed", "evidence": "could not verify"}), "failed")  # only a pass is downgraded

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


class Endings(unittest.TestCase):
    def test_a_stop_after_the_cap_is_spent_is_a_budget_ending(self):
        # The live under-funded run: $0.0813 spent against a $0.08 cap, then the tester produced no file.
        msg = "the tester produced no valid output file twice (last problem: the file x was not written)"
        outcome, message = b.ending_for("other", msg, 0.081273, 0.08)
        self.assertEqual(outcome, "budget_exhausted")
        self.assertIn("$0.0813 spent against a $0.08 cap", message)
        self.assertIn("no valid output file", message)

    def test_a_stop_just_short_of_the_cap_is_a_budget_ending_too(self):
        # The second live run: $0.0768 of $0.08. The tester gets half of what is left, so it runs dry before the cap itself.
        self.assertEqual(b.ending_for("other", "m", 0.076837, 0.08)[0], "budget_exhausted")
        self.assertEqual(b.ending_for("other", "m", 0.0725, 0.08)[0], "budget_exhausted")
        self.assertEqual(b.ending_for("other", "m", 0.07, 0.08)[0], "needs_human")  # 87% of the cap: not out of money

    def test_other_stops_keep_their_names(self):
        self.assertEqual(b.ending_for("other", "m", 0.05, 0.08), ("needs_human", "m"))
        self.assertEqual(b.ending_for("other", "m", None, None), ("needs_human", "m"))
        self.assertEqual(b.ending_for("round_limit", "m", 9.0, 0.08), ("round_limit", "m"))
        self.assertEqual(b.ending_for("time_limit", "m", 9.0, 0.08), ("time_limit", "m"))
        self.assertEqual(b.ending_for("stuck", "m", 0.0, 0.08), ("stuck", "m"))


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

        def invoke(role, label, values, extra_env, cwd, home, note=None):
            attempts.append(label)
            notes.append(note)
            path.write_text('{"results": [' if len(attempts) == 1 else '{"results": []}')
            return 0, 0.1, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        run.art = Path(__import__("tempfile").mkdtemp())
        doc, cost, _ = run.agent_json("tester", "t1", {}, path)
        self.assertEqual(doc, {"results": []})
        self.assertEqual((attempts, notes[0]), (["t1", "t1b"], None))
        self.assertIn("not valid JSON", notes[1])
        self.assertAlmostEqual(cost, 0.2)

    def test_two_bad_attempts_end_in_needs_human_with_the_last_reason(self):
        run = object.__new__(b.BuildRun)
        path = self.write(None)

        def invoke(role, label, values, extra_env, cwd, home, note=None):
            path.write_text("{oops")
            return 0, 0.1, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        run.art = Path(__import__("tempfile").mkdtemp())
        run.state = b.State(run.art / "state.json", "demo", "1", "url")
        with self.assertRaises(b.NeedsHuman) as cm:
            run.agent_json("tester", "t1", {}, path)
        self.assertIn("no valid output file twice", str(cm.exception))
        self.assertIn("last problem: it is not valid JSON", str(cm.exception))
        # the money both attempts spent is in the Report as a stage of its own
        failed = [s for s in run.state.d["stages"] if s["stage"] == "Tester failed"]
        self.assertEqual(len(failed), 1)
        self.assertAlmostEqual(failed[0]["cost_usd"], 0.2)
        self.assertIn("2 attempt(s)", failed[0]["verdict"])

    def test_an_agent_that_spent_its_whole_credential_is_not_given_a_second_attempt(self):
        run = object.__new__(b.BuildRun)
        path = self.write(None)
        run.art = Path(__import__("tempfile").mkdtemp())
        run.state = b.State(run.art / "state.json", "demo", "1", "url")
        labels = []

        def invoke(role, label, values, extra_env, cwd, home, note=None):
            labels.append(label)
            (run.art / f"openhands-{role}-{label}.jsonl").write_text(
                '{"code": "LLMBadRequestError", "detail": "litellm.BadRequestError: OpenAIException - token spending limit exceeded"}\n')
            return 0, 0.55, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        with self.assertRaises(b.NeedsHuman) as cm:
            run.agent_json("tester", "t1", {}, path)
        self.assertEqual(labels, ["t1"])  # no "t1b"
        self.assertIn("spent its whole credential", str(cm.exception))
        self.assertIn("would only repeat it", str(cm.exception))
        stage = run.state.d["stages"][-1]
        self.assertEqual((stage["stage"], stage["cost_usd"]), ("Tester failed", 0.55))
        self.assertIn("1 attempt(s)", stage["verdict"])

    def test_the_spending_limit_message_is_found_at_the_end_of_a_stream_and_a_missing_file_is_not_a_hit(self):
        p = self.write('x' * 400000 + 'token spending limit exceeded')
        self.assertTrue(b.spending_limit_hit(p))
        self.assertFalse(b.spending_limit_hit(self.write("all fine")))
        self.assertFalse(b.spending_limit_hit(Path("/nonexistent/stream.jsonl")))


class RunWatched(unittest.TestCase):
    def test_stalled_only_after_the_limit_and_never_when_off(self):
        self.assertFalse(b.silent_too_long(100, 150, 60))
        self.assertTrue(b.silent_too_long(100, 160, 60))
        self.assertFalse(b.silent_too_long(0, 10**6, 0))

    def test_a_silent_process_is_killed_as_a_stall_and_a_chatty_one_finishes(self):
        import sys, tempfile
        out = Path(tempfile.mkdtemp()) / "o.jsonl"
        started = time.time()
        rc = b.run_watched([sys.executable, "-c", "import time; time.sleep(60)"], None, os.environ.copy(), out, 30, 1, poll=0.2)
        self.assertEqual(rc, "stall")
        self.assertLess(time.time() - started, 10)
        rc = b.run_watched([sys.executable, "-c", "import time\nfor i in range(6):\n print(i, flush=True); time.sleep(0.4)"],
                           None, os.environ.copy(), out, 30, 1.5, poll=0.2)
        self.assertEqual(rc, 0)
        rc = b.run_watched([sys.executable, "-c", "import time\nwhile True:\n print('x', flush=True); time.sleep(0.2)"],
                           None, os.environ.copy(), out, 1, 5, poll=0.2)
        self.assertEqual(rc, "timeout")


class AgentIsolation(unittest.TestCase):
    def test_without_a_user_the_command_is_unchanged(self):
        self.assertEqual(b.agent_command(["openhands", "-t", "x"], {"PATH": "/bin"}, None), ["openhands", "-t", "x"])

    def test_with_a_user_variables_go_by_name_and_never_by_value(self):
        env = {"PATH": "/opt/bin", "LLM_API_KEY": "jwt-secret-value", "HOME": "/srv/agent/run/home-a"}
        cmd = b.agent_command(["openhands", "-t", "x"], env, "agent", "/srv/agent/run/pgid.txt")
        self.assertEqual(cmd[:5], ["sudo", "-n", "-u", "agent", "--preserve-env=LLM_API_KEY,HOME"])
        self.assertNotIn("jwt-secret-value", " ".join(cmd))
        self.assertIn("PATH=/opt/bin", cmd)
        self.assertEqual(cmd[-3:], ["openhands", "-t", "x"])
        self.assertIn("/srv/agent/run/pgid.txt", cmd)

    def test_the_git_credential_travels_in_the_environment_not_the_arguments(self):
        env = b.git_auth_env("Authorization: Basic abc")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "http.extraheader")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "Authorization: Basic abc")

    def test_the_self_check_finds_each_way_isolation_can_fail(self):
        good = {"whoami": "agent\n", "environ": "", "workspace": "", "env_names": "", "sudo": "no\n"}
        self.assertEqual(b.isolation_problems(good), [])
        for bad, text in (({"whoami": "runner\n"}, "different account"), ({"environ": "ISOLATION_MARK=SELF-CHECK-SECRET"}, "environment"),
                          ({"workspace": "app\nrun"}, "workspace"), ({"env_names": "FACTORY_PAT\n"}, "credential"), ({"sudo": "yes\n"}, "sudo")):
            problems = b.isolation_problems({**good, **bad})
            self.assertEqual(len(problems), 1)
            self.assertIn(text, problems[0])


class UiCheckReconcile(unittest.TestCase):
    ok = {"id": "a", "ok": True, "problems": []}
    bad = {"id": "b", "ok": False, "problems": ["role='button': expected it to be visible, but it is not"], "observed": {}}

    def result(self, status="passed", ui=("b",)):
        return {"flag": "f", "check": "c", "status": status, "passed": status == "passed", "evidence": "looked fine", "ui": list(ui)}

    def test_a_scenario_the_browser_saw_fail_cannot_be_reported_as_passed(self):
        out = b.reconcile_ui_checks({"results": [self.result()]}, {"b": self.bad})
        self.assertEqual(b.check_state(out["results"][0]), "failed")
        self.assertIn("ui-check helper observed otherwise", out["results"][0]["evidence"])

    def test_a_scenario_never_run_cannot_be_reported_as_passed_and_a_left_out_failure_is_added(self):
        self.assertEqual(b.check_state(b.reconcile_ui_checks({"results": [self.result(ui=("zzz",))]}, {})["results"][0]), "not_run")
        out = b.reconcile_ui_checks({"results": [self.result(ui=())]}, {"b": self.bad})
        self.assertEqual(b.check_state(out["results"][-1]), "failed")
        self.assertEqual(out["results"][-1]["ui"], ["b"])

    def test_api_and_ui_checks_are_reconciled_separately(self):
        doc = {"results": [{**self.result(), "api": ["a"]}]}
        self.assertEqual(b.check_state(b.reconcile_api_checks(doc, {"a": self.ok})["results"][0]), "passed")
        self.assertEqual(b.check_state(b.reconcile_ui_checks(doc, {"b": self.bad})["results"][0]), "failed")

    def test_the_browser_instructions_appear_only_for_a_change_that_has_something_on_screen(self):
        self.assertTrue(b.wants_ui_check(["frontend/src/App.tsx"], "x"))
        self.assertTrue(b.wants_ui_check(["backend/src/a.ts"], "Add a button that clears the list"))
        self.assertFalse(b.wants_ui_check(["backend/src/a.ts"], "Return 201 from POST /api/notes"))
        self.assertEqual(b.ui_section(False, "/x/ui_check.py"), "")
        self.assertIn("/x/ui_check.py", b.ui_section(True, "/x/ui_check.py"))


class ReportFromHelpers(unittest.TestCase):
    bad = {"id": "b", "name": "n", "ok": False, "problems": ["role='button': expected it to be visible, but it is not"], "observed": {}}
    good = {"id": "g", "name": "n", "ok": True, "problems": []}

    def test_a_missing_report_becomes_the_failures_the_helpers_saw(self):
        doc = b.report_from_helper_failures({}, {"b": self.bad, "g": self.good})
        self.assertEqual([r["status"] for r in doc["results"]], ["failed"])
        self.assertIn("no report", doc["limitations"][0])
        self.assertEqual(b.report_from_helper_failures({"g": self.good}, {}), None)  # nothing failed: nothing to act on
        self.assertEqual(b.report_from_helper_failures({}, {}), None)


class StoryAndFlagReferenceEachOther(unittest.TestCase):
    def test_the_title_carries_the_flag_and_a_retry_does_not_pile_up_tags(self):
        self.assertEqual(b.title_with_flags("app: add a page", ["todo-ui"]), "app: add a page [flag: todo-ui]")
        self.assertEqual(b.title_with_flags("app: add a page [flag: todo-ui]", ["todo-ui"]), "app: add a page [flag: todo-ui]")
        self.assertEqual(b.title_with_flags("app: a [flag: x]", ["y", "z"]), "app: a [flags: y, z]")
        self.assertEqual(b.title_with_flags("app: a", []), "app: a")

    def test_labels_descriptions_and_tags(self):
        self.assertEqual(b.flag_label("todo-ui"), "flag:todo-ui")
        self.assertIsNone(b.flag_label("x" * 60))
        text = b.flag_description("https://github.com/o/r/issues/94", "app: a page [flag: todo-ui]")
        self.assertTrue(text.startswith("https://github.com/o/r/issues/94 "))
        self.assertNotIn("[flag", text)
        self.assertEqual(b.flag_tags("94", "app"), ["intake-94", "app-app"])

    def test_release_creates_the_feature_with_its_story_and_still_works_if_growthbook_refuses_the_extras(self):
        run = object.__new__(b.BuildRun)
        run.app, run.issue, run.issue_url, run.issue_title, run.run_id, run.run_url = "app", "94", "https://github.com/o/r/issues/94", "app: a page", "7", "u"
        run.app_repo, run.state = "o/app", b.State(Path("/tmp/x-state.json"), "app", "94", "u")
        run.state.save = lambda: None
        run.gh = lambda *a, **k: type("R", (), {"stdout": ""})()
        posts = []

        def gb(method, path, body=None):
            if method == "GET":
                return (200, {"projects": [{"id": "p"}]}) if path.startswith("/projects") else (404, {})
            posts.append(body)
            return (400, {}) if "tags" in body else (200, {})
        run.gb = gb
        run.release(["todo-ui"], "sha")
        self.assertEqual(len(posts), 2)  # refused with the extras, created without them
        self.assertEqual(posts[0]["tags"], ["intake-94", "app-app"])
        self.assertIn("issues/94", posts[0]["description"])
        self.assertNotIn("tags", posts[1])
        self.assertEqual(run.state.d["release"]["released"], ["app.feature.todo-ui"])


class RetryOnTheSameIssue(unittest.TestCase):
    def release_run(self, existing_enabled, reuse):
        run = object.__new__(b.BuildRun)
        run.app, run.issue, run.issue_url, run.issue_title, run.run_id, run.run_url = "app", "94", "https://github.com/o/r/issues/94", "t", "7", "u"
        run.app_repo, run.reuse_flags = "o/app", reuse
        run.state = b.State(Path("/tmp/x-state.json"), "app", "94", "u")
        run.state.save = lambda: None
        run.gh = lambda *a, **k: type("R", (), {"stdout": ""})()
        posts = []

        def gb(method, path, body=None):
            if method == "GET":
                if path.startswith("/projects"):
                    return 200, {"projects": [{"id": "p"}]}
                return 200, {"feature": {"environments": {"production": {"enabled": existing_enabled}}}}
            posts.append((path, body))
            return 200, {}
        run.gb = gb
        return run, posts

    def test_the_stories_own_flag_the_watchdog_switched_off_is_released_again(self):
        run, posts = self.release_run(False, ["todo-ui"])
        run.release(["todo-ui"], "sha")
        self.assertEqual(posts, [("/features/app.feature.todo-ui", {"environments": {"production": {"enabled": True, "rules": []}}})])
        self.assertEqual(run.state.d["release"]["released"], ["app.feature.todo-ui"])

    def test_any_other_existing_flag_is_left_exactly_as_it_is(self):
        run, posts = self.release_run(False, [])
        run.release(["todo-ui"], "sha")
        self.assertEqual(posts, [])
        self.assertEqual(run.state.d["release"], {"released": [], "kept": ["app.feature.todo-ui"]})
        run, posts = self.release_run(True, ["todo-ui"])  # already on: nothing to re-enable
        run.release(["todo-ui"], "sha")
        self.assertEqual(posts, [])

    def test_setup_reads_the_retry_state_from_the_issue_comments(self):
        import fixrequest as fr
        hidden = fr.with_retry_state({"attempt": 1, "flags": ["todo-ui"], "history": ["h"], "guidance": "Fix the regression.", "cap": 1.5})
        retry = fr.retry_state([c for c in ["note", hidden]])
        self.assertEqual(retry["flags"], ["todo-ui"])
        self.assertTrue(all(b.SLUG_RE.fullmatch(f) for f in retry["flags"]))


class MisplacedFile(unittest.TestCase):
    def test_a_report_written_in_the_working_directory_is_adopted_but_never_overwrites(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        cwd, run = d / "tree", d / "run"
        cwd.mkdir()
        run.mkdir()
        (cwd / "report.json").write_text('{"a": 1}')
        self.assertTrue(b.adopt_misplaced_file(run / "report.json", cwd))
        self.assertEqual((run / "report.json").read_text(), '{"a": 1}')
        (cwd / "report.json").write_text('{"a": 2}')
        self.assertFalse(b.adopt_misplaced_file(run / "report.json", cwd))  # the real file is never replaced
        self.assertEqual((run / "report.json").read_text(), '{"a": 1}')
        self.assertFalse(b.adopt_misplaced_file(run / "other.json", cwd))
        self.assertFalse(b.adopt_misplaced_file(run / "x.json", None))
        self.assertIn("exactly that absolute path", b.json_problem(run / "missing.json"))


class ModelFallback(unittest.TestCase):
    def run_for(self, answers, roles=None, update=True):
        """A BuildRun whose provider answers per model id (status, body)."""
        run = object.__new__(b.BuildRun)
        run.update_intake = update
        run.cfg = {"provider": {"base_url": "https://llm"}, "roles": roles or {
            "coder": {"model": "a/coder", "fallback_model": "z/fallback"}, "tester": {"model": "t/tester"}, "reviewer": {"model": "r/rev"}, "planner": {"model": "p/plan"}}}
        run.state = b.State(Path("/tmp/x-state.json"), "app", "1", "u")
        run.state.save = lambda: None
        asked = []

        def fake_http(method, url, token=None, body=None, timeout=60):
            asked.append(body["model"])
            return answers.get(body["model"], (200, {}))
        return run, asked, fake_http

    def test_a_missing_model_is_replaced_by_its_fallback_for_this_run_and_the_swap_is_recorded(self):
        run, asked, fake = self.run_for({"a/coder": (404, {"error": {"message": "Model not found"}})})
        with mock.patch.object(b, "http", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertEqual(run.cfg["roles"]["coder"]["model"], "z/fallback")
        self.assertEqual(run.state.d["fallbacks"]["coder"], {"from": "a/coder", "to": "z/fallback"})
        self.assertEqual(run.cfg["roles"]["tester"]["model"], "t/tester")  # a role whose model is served is left alone

    def test_a_missing_model_with_no_fallback_stops_the_run_with_the_reason(self):
        run, _, fake = self.run_for({"r/rev": (400, {"error": {"message": "The model `r/rev` does not exist"}})})
        with mock.patch.object(b, "http", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            with self.assertRaises(b.NeedsHuman) as ctx:
                run.check_models()
        self.assertIn("r/rev", str(ctx.exception))
        self.assertIn("no `fallback_model`", str(ctx.exception))

    def test_a_missing_fallback_is_also_a_stop_and_each_model_is_asked_once(self):
        run, asked, fake = self.run_for({"a/coder": (404, {}), "z/fallback": (404, {})})
        with mock.patch.object(b, "http", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            with self.assertRaises(b.NeedsHuman):
                run.check_models()
        self.assertEqual(len(asked), len(set(asked)))

    def test_all_models_answering_changes_nothing_and_a_zero_balance_is_still_provider_blocked(self):
        run, _, fake = self.run_for({})
        with mock.patch.object(b, "http", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertNotIn("fallbacks", run.state.d)
        run, _, fake = self.run_for({"a/coder": (402, {})})
        with mock.patch.object(b, "http", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            with self.assertRaises(b.ProviderBlocked):
                run.check_models()

    def test_a_first_build_does_not_check_the_planner(self):
        run, asked, fake = self.run_for({}, update=False)
        with mock.patch.object(b, "http", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertNotIn("p/plan", asked)
        run, asked, fake = self.run_for({})  # an update does ask for the planner's model
        with mock.patch.object(b, "http", fake), mock.patch.dict(__import__("os").environ, {"DEEPINFRA_API_KEY": "k"}):
            run.check_models()
        self.assertIn("p/plan", asked)

    def test_the_status_of_a_model_is_read_from_the_answer(self):
        for answer, expected in (((200, {}), "ok"), ((404, "x"), "missing"), ((400, {"error": "model foo not found"}), "missing"),
                                 ((500, "boom"), "unknown"), ((429, "slow"), "unknown")):
            with mock.patch.object(b, "http", lambda *a, **k: answer):
                self.assertEqual(b.model_status("https://llm", "k", "m"), expected, answer)


class ScoreboardCategories(unittest.TestCase):
    def test_the_scoreboard_counts_blocking_findings_by_category_and_tester_checks_apart(self):
        record = {"counts": {}, "checks": []}
        blocking = [{"source": "reviewer", "summary": "a", "category": "test_quality"}, {"source": "reviewer", "summary": "b", "category": "test_quality"},
                    {"source": "tester", "summary": "c"}]
        self.assertEqual(b.scoreboard_entry(1, "sha", record, blocking)["categories"], {"test_quality": 2, "tester_check": 1})


class CheckProblem(unittest.TestCase):
    """The Orchestrator's own `npm run check` on the coder's commit, before the reviewer."""

    def make(self, scripts, exit_code=0, output="src/a.ts(3,1): error TS2322"):
        import tempfile
        run = object.__new__(b.BuildRun)
        run.agent_user = None
        run.app_dir = Path(tempfile.mkdtemp(prefix="check-test-"))
        (run.app_dir / "package.json").write_text(json.dumps({"scripts": scripts}))
        run.restore_tree = lambda *a, **k: None
        bin_dir = Path(tempfile.mkdtemp(prefix="npm-stub-"))
        stub = bin_dir / "npm"
        stub.write_text(f"#!/bin/sh\necho '{output}'\nexit {exit_code}\n")
        stub.chmod(0o755)
        self.patch = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        return run

    def test_a_passing_check_is_no_problem(self):
        self.assertIsNone(self.make({"check": "tsc"}).check_problem())

    def test_a_failing_check_tells_the_coder_the_errors(self):
        problem = self.make({"check": "tsc"}, exit_code=2).check_problem()
        self.assertIn("npm run check", problem)
        self.assertIn("TS2322", problem)

    def test_an_app_without_a_check_script_is_skipped(self):
        self.assertIsNone(self.make({"test": "x"}, exit_code=2).check_problem())


if __name__ == "__main__":
    unittest.main()
