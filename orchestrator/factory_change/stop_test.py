import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from factory_change import stop  # noqa: E402


class Ending(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        self.number = self.gh.add(5)
        patcher = mock.patch.object(github, "run", self.gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_ending_is_named_and_commented_on_the_intake(self):
        for outcome in (stop.MERGED, stop.AWAITING_HUMAN, stop.REFUSED, stop.PAUSED):
            self.assertEqual(stop.end("o/f", "t", 5, outcome, "because"), outcome)
        self.assertEqual(len(self.gh.comments[5]), 4)
        self.assertIn("awaiting human", self.gh.comments[5][1])

    def test_needs_human_labels_the_intake(self):
        stop.end("o/f", "t", 5, stop.NEEDS_HUMAN, "no reproduction")
        self.assertIn("needs-human", [x["name"] for x in self.gh.issues[5]["labels"]])

    def test_an_unknown_ending_is_a_bug(self):
        with self.assertRaises(AssertionError):
            stop.end("o/f", "t", 5, "failed", "x")


if __name__ == "__main__":
    unittest.main()
