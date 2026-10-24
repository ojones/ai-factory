import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run import endings  # noqa: E402


class Endings(unittest.TestCase):
    def test_a_stop_after_the_cap_is_spent_is_a_budget_ending(self):
        msg = "the tester produced no valid output file twice (last problem: the file x was not written)"
        outcome, message = endings.ending_for("other", msg, 0.081273, 0.08)
        self.assertEqual(outcome, "budget_exhausted")
        self.assertIn("$0.0813 spent against a $0.08 cap", message)
        self.assertIn("no valid output file", message)

    def test_a_stop_just_short_of_the_cap_is_a_budget_ending_too(self):
        self.assertEqual(endings.ending_for("other", "m", 0.076837, 0.08)[0], "budget_exhausted")
        self.assertEqual(endings.ending_for("other", "m", 0.0725, 0.08)[0], "budget_exhausted")
        self.assertEqual(endings.ending_for("other", "m", 0.07, 0.08)[0], "needs_human", msg="87% of the cap: not out of money")

    def test_other_stops_keep_their_names(self):
        self.assertEqual(endings.ending_for("other", "m", 0.05, 0.08), ("needs_human", "m"))
        self.assertEqual(endings.ending_for("other", "m", None, None), ("needs_human", "m"))
        self.assertEqual(endings.ending_for("round_limit", "m", 9.0, 0.08), ("round_limit", "m"))
        self.assertEqual(endings.ending_for("time_limit", "m", 9.0, 0.08), ("time_limit", "m"))


if __name__ == "__main__":
    unittest.main()
