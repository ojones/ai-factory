import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from planning import fix_for  # noqa: E402

FIX = {"fix_for": 12, "origin_parent": 5, "attempt": 1}


class PlanningAFix(unittest.TestCase):
    def test_a_fix_is_told_to_plan_one_small_change_set_and_an_ordinary_task_is_untouched(self):
        told = fix_for.task_for("Add tags", FIX)
        self.assertIn("Plan exactly ONE change set", told)
        self.assertTrue(told.endswith("Add tags"))
        self.assertEqual(fix_for.task_for("Add tags", None), "Add tags")

    def test_the_note_leaves_the_flag_to_the_planner_like_any_other_child(self):
        self.assertNotIn("flag", fix_for.NOTE.lower())

    def test_a_fix_is_capped_at_one_change_set_and_anything_else_keeps_its_cap(self):
        self.assertEqual(fix_for.max_change_sets(FIX, 6), 1)
        self.assertEqual(fix_for.max_change_sets(None, 6), 6)
        self.assertFalse(hasattr(fix_for, "apply"))


if __name__ == "__main__":
    unittest.main()
