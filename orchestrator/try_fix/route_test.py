import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import route  # noqa: E402


class Routing(unittest.TestCase):
    def test_the_cause_decides_where_it_goes(self):
        for c in ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap"):
            self.assertEqual(route.route(c), "factory", c)
        for c in ("spec_ambiguity", "model_limit", "regression"):
            self.assertEqual(route.route(c), "app", c)
        for c in ("infra", "unknown", None, "nonsense"):
            self.assertEqual(route.route(c), "info", c)

    def test_a_regression_is_fixed_forward_unless_the_cause_is_the_factorys(self):
        self.assertEqual(route.route(route.inferred_category(None, "regression")), "app")
        self.assertEqual(route.route(route.inferred_category("prompt_gap", "regression")), "factory")

    def test_failed_checks_send_the_story_back_to_its_own_code_unless_the_cause_is_the_factorys(self):
        for category in (None, "infra", "unknown", "model_limit"):
            self.assertEqual(route.route(route.inferred_category(category, "round_limit", True)), "app", category)
        self.assertEqual(route.route(route.inferred_category(None, "round_limit", False)), "info")
        self.assertEqual(route.route(route.inferred_category("prompt_gap", "round_limit", True)), "factory")

    def test_a_run_that_ran_out_of_money_or_time_was_too_big_for_its_limits(self):
        for outcome in ("budget_exhausted", "time_limit"):
            self.assertEqual(route.route(route.inferred_category(None, outcome)), "app", outcome)
        for outcome in ("round_limit", "needs_human", "crash", "stuck"):
            self.assertEqual(route.route(route.inferred_category(None, outcome)), "info", outcome)
        self.assertEqual(route.inferred_category("plan_gap", "budget_exhausted"), "plan_gap")  # a named structural cause wins
        self.assertEqual(route.route(route.inferred_category("prompt_gap", "budget_exhausted")), "app")  # a tester that ran dry looks like a prompt gap
        self.assertEqual(route.route(route.inferred_category("prompt_gap", "round_limit")), "factory")


if __name__ == "__main__":
    unittest.main()
