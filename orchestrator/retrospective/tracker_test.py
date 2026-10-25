import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import tracker  # noqa: E402

STATE = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass",
         "run_url": "http://run", "issue_number": "7", "spent_usd": 1.5, "commits": ["a"],
         "blocking": [{"summary": "The new route is mounted before the health route"}],
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2, "usage": {"seconds": 120, "calls": 30}},
                    {"stage": "Release", "round": "-", "verdict": "x", "cost_usd": 0, "usage": None}]}


class Recurrence(unittest.TestCase):
    ISSUES = [{"number": 4, "title": "Lesson [many_rounds] aa", "state": "CLOSED"},
              {"number": 9, "title": "Lesson [budget_high] bb", "state": "OPEN"},
              {"number": 5, "title": "Lesson [many_rounds] aa", "state": "OPEN"}]

    def test_open_beats_closed_and_only_exact_titles_match(self):
        self.assertEqual(tracker.pick_existing(self.ISSUES, "Lesson [many_rounds] aa"), (5, 4))
        self.assertEqual(tracker.pick_existing(self.ISSUES, "Lesson [budget_high] bb"), (9, None))
        self.assertEqual(tracker.pick_existing(self.ISSUES, "Lesson [slow_stage] cc"), (None, None))
        self.assertEqual(tracker.pick_existing([{"number": 1, "title": "Lesson [x] y", "state": "closed"}], "Lesson [x] y"), (None, 1))


if __name__ == "__main__":
    unittest.main()
