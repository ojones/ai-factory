import unittest
from pathlib import Path

from shared import outcomes


class Outcomes(unittest.TestCase):
    def test_a_good_ending_is_a_release_or_nothing_to_release_or_a_plan(self):
        self.assertEqual(set(outcomes.OK), {"released", "nothing_to_release", "planned"})
        self.assertTrue(all(outcomes.is_ok(o) for o in outcomes.OK))

    def test_an_answer_is_not_a_good_ending_and_not_a_failure_to_learn_from(self):
        self.assertEqual(set(outcomes.ANSWERED), {"refused", "awaiting_secret"})
        for o in outcomes.ANSWERED:
            self.assertTrue(outcomes.is_answered(o))
            self.assertFalse(outcomes.is_ok(o))

    def test_a_blocked_provider_and_a_switched_off_release_are_neither(self):
        for o in (outcomes.PROVIDER_BLOCKED, outcomes.WATCHDOG_DISABLED, "stuck", "needs_human", "crash", "regression"):
            self.assertFalse(outcomes.is_ok(o))
            self.assertFalse(outcomes.is_answered(o))


    def test_no_other_module_keeps_its_own_copy_of_the_good_endings(self):
        # Four modules used to mirror this tuple, and a test kept them in step (INV-24).
        root = Path(__file__).resolve().parent.parent
        copies = [p.name for p in root.rglob("*.py") if p.name != "outcomes.py" and not p.name.endswith("_test.py") and '"nothing_to_release", "planned"' in p.read_text()]
        self.assertEqual(copies, [])


if __name__ == "__main__":
    unittest.main()
