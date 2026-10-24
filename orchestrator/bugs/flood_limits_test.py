import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bugs import flood_limits  # noqa: E402

CFG = {"enabled": True, "min_occurrences": 3, "bugs_per_app_per_day": 2}
GROUPS = {"aaaaaaaa": {"count": 5, "message": "m", "frame": ""}, "bbbbbbbb": {"count": 2, "message": "n", "frame": ""},
          "cccccccc": {"count": 9, "message": "o", "frame": ""}}


class Decide(unittest.TestCase):
    def test_below_the_threshold_nothing_is_reported(self):
        self.assertEqual(flood_limits.decide({"bbbbbbbb": GROUPS["bbbbbbbb"]}, {}, 0, 0, CFG), ([], []))

    def test_the_most_frequent_error_goes_first_and_only_one_bug_is_open_per_app(self):
        self.assertEqual(flood_limits.decide(GROUPS, {}, 0, 0, CFG), (["cccccccc"], []))
        self.assertEqual(flood_limits.decide(GROUPS, {}, 1, 0, CFG), ([], []))

    def test_a_known_error_gets_a_comment_not_a_second_bug(self):
        self.assertEqual(flood_limits.decide(GROUPS, {"cccccccc": 7}, 1, 0, CFG), ([], ["cccccccc"]))

    def test_the_daily_limit_stops_new_bugs(self):
        self.assertEqual(flood_limits.decide(GROUPS, {}, 0, 2, CFG), ([], []))

    def test_a_defect_report_waits_for_an_open_bug_or_the_daily_limit_and_one_goes_per_scan(self):
        self.assertTrue(flood_limits.defects_room(0, 0, 0, CFG))
        self.assertFalse(flood_limits.defects_room(1, 0, 0, CFG))
        self.assertFalse(flood_limits.defects_room(0, 2, 0, CFG))
        self.assertFalse(flood_limits.defects_room(0, 0, 1, CFG))


if __name__ == "__main__":
    unittest.main()
