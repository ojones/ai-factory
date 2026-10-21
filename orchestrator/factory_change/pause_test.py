import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from factory_change import pause  # noqa: E402


class Breaker(unittest.TestCase):
    def test_a_failure_at_the_watched_stage_trips_it(self):
        later = [{"failed": False, "stage": "test"}, {"failed": True, "stage": "review"}]
        self.assertIn("same stage (review)", pause.breaker_reason("review", later, 0))

    def test_a_failure_at_another_stage_does_not(self):
        self.assertIsNone(pause.breaker_reason("review", [{"failed": True, "stage": "test"}], 0))

    def test_a_regression_trips_it(self):
        self.assertIn("regression", pause.breaker_reason("review", [{"regression": True}], 0))

    def test_two_ineffective_fixes_in_a_row_trip_it(self):
        self.assertIsNone(pause.breaker_reason("review", [], 1))
        self.assertIn("2 merged changes", pause.breaker_reason("review", [], 2))


class Pausing(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        patcher = mock.patch.object(github, "run", self.gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_pause_is_an_open_issue_with_the_label_until_a_person_closes_it(self):
        self.assertFalse(pause.is_paused("o/f", "t"))
        pause.pause("o/f", "t", "a regression", "https://x/pull/1")
        self.assertTrue(pause.is_paused("o/f", "t"))
        self.gh.issues[next(iter(self.gh.issues))]["state"] = "closed"
        self.assertFalse(pause.is_paused("o/f", "t"))


if __name__ == "__main__":
    unittest.main()
