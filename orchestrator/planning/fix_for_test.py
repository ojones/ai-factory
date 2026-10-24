import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from planning import fix_for, validate_plan  # noqa: E402

TICKET = ("#### What happened\n\nround limit reached\n\nRun: https://x/run/1\n\n#### Requirements\n\n1. POST /api/todos with blank text answers 400\n"
          "2. A test covers blank text\n\n#### Target\n\nThe Managed App (its code or its request).\n")


class PlanFromTicket(unittest.TestCase):
    def test_the_numbered_requirements_become_the_criteria_of_one_change_set_with_a_flag(self):
        got = fix_for.plan_from_ticket(TICKET)
        (cs,) = got["change_sets"]
        self.assertEqual(cs["criteria"], ["POST /api/todos with blank text answers 400", "A test covers blank text"])
        self.assertEqual((cs["title"], cs["flag"], cs["depends_on"]), ("Fix: round limit reached", True, []))
        self.assertEqual(got["feasibility"], {"status": "ok"})

    def test_the_plan_passes_the_same_validation_as_any_plan(self):
        problems, questions = validate_plan.validate_plan(fix_for.plan_from_ticket(TICKET), "update", 1, 6)
        self.assertEqual((problems, questions), ([], []))

    def test_a_ticket_with_no_numbered_requirements_makes_a_plan_that_fails_validation(self):
        problems, _ = validate_plan.validate_plan(fix_for.plan_from_ticket("#### What happened\n\nboom\n"), "update", 1, 6)
        self.assertTrue(problems)

    def test_more_requirements_than_the_limit_fail_validation(self):
        many = "#### Requirements\n\n" + "\n".join(f"{i}. does thing {i}" for i in range(1, 8)) + "\n"
        problems, _ = validate_plan.validate_plan(fix_for.plan_from_ticket(many), "update", 1, 6)
        self.assertTrue(any("acceptance criteria" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
