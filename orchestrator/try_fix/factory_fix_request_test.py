import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402

from try_fix import factory_fix_request as ffr  # noqa: E402

DOC = {"how_found": "The tester saw it.", "root_cause": "No trimming.", "what_it_takes": ["Blank text is rejected"], "requirements": ["A test covers it"]}
VERDICT = {"key": "d7a70fbaf6", "cause": "plan_gap", "reason": "the plan split it wrongly",
           "event": {"app": "demo", "story": 12, "source": "build_run", "severity": "failure", "summary": "round limit reached"}}


class Filing(unittest.TestCase):
    def file(self, existing=None, target="factory"):
        calls = []

        def fake(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps(existing or []))
            if args[:2] == ["issue", "create"]:
                return mock.Mock(stdout="https://github.com/o/f/issues/80\n")
            return mock.Mock(stdout="")

        with mock.patch.object(github, "run", fake), mock.patch.object(github, "ensure_label"):
            return ffr.file_bug_request("o/f", "tok", VERDICT, DOC, "https://x/run/9", target), calls

    def test_one_fingerprint_per_app_child_and_route(self):
        a = ffr.fingerprint("demo", "12", "factory")
        self.assertEqual(a, ffr.fingerprint("demo", "12", "factory"))
        self.assertNotEqual(a, ffr.fingerprint("demo", "12", "info"))
        self.assertNotEqual(a, ffr.fingerprint("demo", "67", "factory"))

    def test_a_factory_cause_files_one_issue_for_a_person_and_nothing_reads_it_back(self):
        got, calls = self.file()
        self.assertEqual(got, {"target": "factory", "action": "fix_request", "number": 80, "url": "https://github.com/o/f/issues/80"})
        create = next(c for c in calls if c[:2] == ["issue", "create"])
        self.assertIn("factory-fix-request", create[create.index("--label") + 1])
        self.assertNotIn("failed-child", create[create.index("--body") + 1])

    def test_no_cause_files_an_information_issue_only(self):
        _, calls = self.file(target="info")
        create = next(c for c in calls if c[:2] == ["issue", "create"])
        self.assertEqual(create[create.index("--label") + 1], "fix-request")

    def test_a_second_failure_of_the_same_child_comments_instead_of_filing_again(self):
        fp = ffr.fingerprint("demo", 12, "factory")
        got, calls = self.file([{"number": 80, "title": f"Fix request [{fp}] [d7a70fbaf6]: plan_gap in demo", "url": "https://github.com/o/f/issues/80"}])
        self.assertEqual(got["url"], "https://github.com/o/f/issues/80")
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertIn("Failed again", comment[comment.index("--body") + 1])


if __name__ == "__main__":
    unittest.main()
