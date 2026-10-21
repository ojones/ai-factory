import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import http_client  # noqa: E402

from build_run import review_code, verify_deployed_app  # noqa: E402


def finding(**over):
    return {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "x", "evidence": "e",
            "file": "backend/src/a.ts", "line": "3", "requirement": "", "suggested_fix": "", "repro": "", **over}


class Verdicts(unittest.TestCase):
    def test_model_verdict_field_is_ignored(self):
        clean, blocking, _ = review_code.derive_review({"verdict": "clean", "findings": [finding()]})
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)

    def test_a_backed_blocking_finding_blocks(self):
        for f in (finding(), finding(category="security", evidence_kind="repro", file="", line="", repro="curl -i /x"),
                  finding(category="requirement_not_met"), finding(category="flag_misuse"), finding(category="data_safety"), finding(category="test_quality")):
            clean, blocking, _ = review_code.derive_review({"findings": [f]})
            self.assertEqual((clean, len(blocking)), (False, 1), f["category"])

    def test_a_blocking_finding_the_fields_do_not_back_is_minor_with_the_reason(self):
        for f, why in ((finding(evidence_kind="opinion"), "evidence `opinion`"),
                       (finding(file="", line=""), "not backed by a file and line"),
                       (finding(line=""), "not backed by a file and line"),
                       (finding(evidence_kind="repro", repro=""), "not backed by a repro"),
                       (finding(category="style"), "category `style` cannot block"),
                       (finding(category="duplication"), "cannot block"), (finding(category="other"), "cannot block")):
            clean, blocking, minor = review_code.derive_review({"findings": [f]})
            self.assertEqual((clean, blocking), (True, []), why)
            self.assertEqual(minor[0]["severity"], "minor")
            self.assertIn(why, minor[0]["downgraded"])

    def test_a_minor_finding_is_never_raised_whatever_its_fields(self):
        clean, blocking, minor = review_code.derive_review({"findings": [finding(severity="minor", category="security")]})
        self.assertEqual((clean, blocking, len(minor)), (True, [], 1))
        self.assertNotIn("downgraded", minor[0])

    def test_findings_without_the_structure_are_refused_so_the_reviewer_is_asked_again(self):
        bad = finding()
        del bad["category"]
        for f in (bad, finding(category="nonsense"), finding(evidence_kind="vibes")):
            with self.assertRaises(ValueError):
                review_code.derive_review({"findings": [f]})

    def test_findings_reach_the_coder_with_whatever_detail_they_carry(self):
        raw = {"file": "backend/src/app.ts", "line": "12", "repro": "curl -i /x", "suggested_fix": "", "requirement": None}
        view = review_code.finding_view("reviewer", "no health route", "app.use(r)", raw)
        self.assertEqual(view["file"], "backend/src/app.ts")
        self.assertNotIn("suggested_fix", view)
        text = review_code.describe_finding(view)
        self.assertIn("Where: backend/src/app.ts:12", text)
        self.assertIn("Repro: curl -i /x", text)
        self.assertEqual(review_code.describe_finding(review_code.finding_view("tester", "a: b", "", {})), "- [tester] a: b")

    def test_minor_only_is_clean(self):
        self.assertTrue(review_code.derive_review({"findings": [finding(severity="minor")]})[0])

    def test_review_without_findings_list_is_invalid(self):
        with self.assertRaises(ValueError):
            review_code.derive_review({"verdict": "clean"})

    def test_a_flagless_test_needs_at_least_one_result(self):
        self.assertTrue(verify_deployed_app.derive_test({"results": [{"flag": "", "passed": True}]}, [])[0])
        with self.assertRaises(ValueError):
            verify_deployed_app.derive_test({"results": []}, [])

    def test_tester_passed_is_derived_and_flags_need_coverage(self):
        doc = {"passed": True, "results": [{"flag": "a", "check": "x", "passed": True}]}
        self.assertTrue(verify_deployed_app.derive_test(doc, ["a"])[0])
        passed, failures = verify_deployed_app.derive_test(doc, ["a", "b"])
        self.assertFalse(passed)
        self.assertEqual(failures[0]["flag"], "b")

    def test_tester_one_failure_fails(self):
        doc = {"passed": True, "results": [{"flag": "a", "passed": True}, {"flag": "a", "passed": False}]}
        self.assertFalse(verify_deployed_app.derive_test(doc, ["a"])[0])

    def test_empty_results_with_flags_fails(self):
        self.assertFalse(verify_deployed_app.derive_test({"results": []}, ["a"])[0])


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
        ctx = review_code.build_review_context(self.git, "base1234", "abc12345", 10000)
        for needle in ("Build notes.", "DIFF TEXT", "1: a\n2: b", "# File at abc12345: backend/src/app.ts",
                       "# File at abc12345: backend/src/feature-flags.ts",
                       "- notes-delete: ", "- unused: NOT USED ANYWHERE"):
            self.assertIn(needle, ctx)
        self.assertNotIn("package-lock.json", ctx.split("# Where each")[0].replace("DIFF TEXT", ""))

    def test_a_change_too_big_for_one_prompt_is_refused_not_truncated(self):
        with self.assertRaises(review_code.ContextTooLarge):
            review_code.build_review_context(self.git, "base1234", "abc12345", 50)

    def test_call_retries_overload_then_returns_the_document(self):
        replies = [(429, "busy"), (200, {"choices": [{"message": {"content": '{"analysis": "a", "findings": [], "verdict": "clean"}'}}],
                                         "usage": {"prompt_tokens": 5}})]
        orig, orig_sleep = http_client.request, time.sleep
        http_client.request, time.sleep = (lambda *a, **k: replies.pop(0)), (lambda s: None)
        try:
            doc, usage = review_code.single_call_review("u", "k", "m", "sys", "user")
        finally:
            http_client.request, time.sleep = orig, orig_sleep
        self.assertEqual(doc["verdict"], "clean")
        self.assertEqual(usage["prompt_tokens"], 5)

    def test_unusable_replies_end_in_a_failure_the_caller_can_fall_back_on(self):
        orig, orig_sleep = http_client.request, time.sleep
        http_client.request, time.sleep = (lambda *a, **k: (200, {"choices": [{"message": {"content": "not json"}}]})), (lambda s: None)
        try:
            with self.assertRaises(review_code.FastReviewFailed):
                review_code.single_call_review("u", "k", "m", "sys", "user", attempts=2)
        finally:
            http_client.request, time.sleep = orig, orig_sleep


if __name__ == "__main__":
    unittest.main()
