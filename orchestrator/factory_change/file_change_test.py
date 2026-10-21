import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from factory_change import file_change, pause  # noqa: E402


def finding(**kw):
    return dict({"fingerprint": "ab12cd34", "summary": "The plan step drops a child", "failure": "Child 3 is never filed.",
                 "requirements": ["Every change set in the plan is filed as a sub-issue", "A plan with a missing child is rejected before filing"],
                 "reproduction": "planning.file_children_test.Filing.test_a_child_is_kept", "evidence": "https://github.com/o/f/actions/runs/1"}, **kw)


class Filing(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        patcher = mock.patch.object(github, "run", self.gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def file(self, **kw):
        return file_change.file_change("o/f", "t", finding(**kw), 8)

    def test_a_well_formed_finding_is_filed_with_the_label(self):
        out = self.file()
        self.assertEqual(out["action"], "filed")
        issue = self.gh.issues[out["number"]]
        self.assertIn("factory-change", [x["name"] for x in issue["labels"]])
        self.assertEqual(file_change.requirements_of(issue["body"]), finding()["requirements"])

    def test_a_vague_requirement_or_a_bad_reproduction_is_refused_before_filing(self):
        out = self.file(requirements=["Improve the planner"], reproduction="somewhere in the tests")
        self.assertEqual(out["action"], "refused")
        self.assertEqual(len(out["problems"]), 2)
        self.assertEqual(self.gh.issues, {})

    def test_no_reproduction_is_allowed_for_the_coder_to_write(self):
        self.assertEqual(self.file(reproduction="none")["action"], "filed")

    def test_a_repeat_adds_a_comment_instead_of_a_second_ticket(self):
        first = self.file()["number"]
        again = self.file()
        self.assertEqual((again["action"], again["number"]), ("seen_again", first))
        self.assertIn("Seen again", self.gh.comments[first][0])
        self.assertEqual(len(self.gh.issues), 1)

    def test_a_closed_ticket_that_returns_is_reopened_as_ineffective(self):
        first = self.file()["number"]
        self.gh.issues[first]["state"] = "closed"
        self.file()
        self.assertEqual(self.gh.issues[first]["state"], "open")
        self.assertIn("fix-ineffective", [x["name"] for x in self.gh.issues[first]["labels"]])

    def test_nothing_is_filed_while_the_process_is_paused(self):
        pause.pause("o/f", "t", "a regression")
        before = len(self.gh.issues)
        self.assertEqual(self.file()["action"], "paused")
        self.assertEqual(len(self.gh.issues), before)


if __name__ == "__main__":
    unittest.main()
