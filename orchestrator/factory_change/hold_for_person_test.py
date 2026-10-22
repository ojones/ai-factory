import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402

from factory_change import hold_for_person, stop  # noqa: E402


class HoldForPerson(unittest.TestCase):
    def hold(self):
        with mock.patch.object(github, "run") as ran:
            outcome = hold_for_person.hold("o/f", "tok", 12, "https://github.com/o/f/pull/9", ["orchestrator/build_run/run.py", "agents/profiles.yml"])
        return outcome, ran

    def test_the_pr_is_told_to_wait_naming_every_control_path_file(self):
        _, ran = self.hold()
        pr_comment = ran.call_args_list[0]
        self.assertEqual(pr_comment.args[0][:3], ["pr", "comment", "https://github.com/o/f/pull/9"])
        body = pr_comment.args[0][pr_comment.args[0].index("--body") + 1]
        self.assertIn("`orchestrator/build_run/run.py`, `agents/profiles.yml`", body)
        self.assertIn("does not merge itself", body)

    def test_the_child_ends_awaiting_a_person_and_is_told_where(self):
        outcome, ran = self.hold()
        self.assertEqual(outcome, stop.AWAITING_HUMAN)
        child_comment = ran.call_args_list[1].args[0]
        self.assertEqual(child_comment[:3], ["issue", "comment", "12"])
        self.assertIn("https://github.com/o/f/pull/9", child_comment[child_comment.index("--body") + 1])


if __name__ == "__main__":
    unittest.main()
