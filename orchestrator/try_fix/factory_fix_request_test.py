import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402

from try_fix import factory_fix_request as ffr  # noqa: E402

FACTS = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass", "run_url": "https://x/run/9",
         "issue_number": "12", "review_passes": 4, "spent_usd": 0.61, "cap_usd": 0.75, "commits": ["a", "b"],
         "final_blocking": ["the change is not behind the flag the spec names"], "recurring_findings": []}
REVERT = {"status": "rolled_back", "restored": "0123456789ab", "deploy": "healthy"}
RESULT = {"category": "spec_ambiguity", "root_cause": "The request contradicts itself.", "change_summary": "none", "requirements": ["x"]}


class Filing(unittest.TestCase):
    def file(self, existing=None, target="factory", result=RESULT):
        calls = []

        def fake(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps(existing or []))
            if args[:2] == ["issue", "create"]:
                return mock.Mock(stdout="https://github.com/o/f/issues/80\n")
            return mock.Mock(stdout="")

        with mock.patch.object(github, "run", fake), mock.patch.object(github, "ensure_label"):
            return ffr.file_request("o/f", "tok", FACTS, result, REVERT, target, "prompt_gap"), calls

    def test_the_marker_names_the_failed_child_and_is_read_back(self):
        self.assertEqual(ffr.read_failed_child("x\n" + ffr.failed_child_marker(12) + "\n"), 12)
        self.assertIsNone(ffr.read_failed_child("no marker"))

    def test_one_fingerprint_per_app_child_and_route(self):
        a = ffr.fingerprint("demo", "12", "factory")
        self.assertEqual(a, ffr.fingerprint("demo", "12", "factory"))
        self.assertNotEqual(a, ffr.fingerprint("demo", "12", "info"))
        self.assertNotEqual(a, ffr.fingerprint("demo", "67", "factory"))

    def test_a_factory_cause_files_an_issue_for_the_factory_run_that_records_the_failed_child(self):
        got, calls = self.file()
        self.assertEqual(got, {"action": "fix_request", "url": "https://github.com/o/f/issues/80"})
        create = next(c for c in calls if c[:2] == ["issue", "create"])
        self.assertIn("factory-fix-request", create[create.index("--label") + 1])
        self.assertEqual(ffr.read_failed_child(create[create.index("--body") + 1]), 12)

    def test_no_cause_files_an_information_issue_only(self):
        _, calls = self.file(target="info")
        create = next(c for c in calls if c[:2] == ["issue", "create"])
        self.assertEqual(create[create.index("--label") + 1], "fix-request")

    def test_a_second_failure_of_the_same_child_comments_instead_of_filing_again(self):
        fp = ffr.fingerprint("demo", "12", "factory")
        got, calls = self.file([{"number": 80, "title": f"Fix request [{fp}]: plan_gap in demo", "url": "https://github.com/o/f/issues/80"}])
        self.assertEqual(got["url"], "https://github.com/o/f/issues/80")
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertIn("Failed again", comment[comment.index("--body") + 1])


if __name__ == "__main__":
    unittest.main()
