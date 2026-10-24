import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import cause, story_report  # noqa: E402


def facts(outcome, **kw):
    return {"outcome": outcome, "message": "m", "run_url": "u", "review_passes": 1, "spent_usd": 0.2, "cap_usd": 2.0, "commits": [], "recurring_findings": [],
            "final_minor": [], "stages": [], **kw}


class NamingTheCause(unittest.TestCase):
    def test_the_agents_category_decides_where_the_cause_goes(self):
        self.assertEqual(cause.name_cause(facts("round_limit"), {"category": "prompt_gap"}), {"category": "prompt_gap", "route": "factory"})
        self.assertEqual(cause.name_cause(facts("round_limit"), {"category": "spec_ambiguity"}), {"category": "spec_ambiguity", "route": "app"})
        self.assertEqual(cause.name_cause(facts("crash"), {"category": "infra"}), {"category": "infra", "route": "info"})

    def test_it_is_inferred_from_the_ending_when_the_agent_did_not_run(self):
        self.assertEqual(cause.name_cause(facts("budget_exhausted"), None), {"category": "model_limit", "route": "app"})
        self.assertEqual(cause.name_cause(facts("regression"), None), {"category": "regression", "route": "app"})
        self.assertEqual(cause.name_cause(facts("round_limit", bugs=[{"kind": "dark"}]), None)["route"], "app", msg="failed checks: retry the story")
        self.assertEqual(cause.name_cause(facts("round_limit"), None), {"category": None, "route": "info"}, msg="no cause: a person decides")

    def test_a_factory_cause_is_never_overridden_by_a_spent_budget(self):
        self.assertEqual(cause.name_cause(facts("budget_exhausted"), {"category": "orchestrator_gap"}), {"category": "orchestrator_gap", "route": "factory"})

    def test_the_story_says_what_the_cause_leads_to_only_when_the_run_did_not_release(self):
        text = story_report.render_retrospective(facts("round_limit"), [], [], None, (), {"category": "plan_gap", "route": "factory"})
        self.assertIn("Cause: `plan_gap`, handled as: a fix request for the Factory.", text)
        released = story_report.render_retrospective(facts("released"), [], [], None, (), {"category": None, "route": "info"})
        self.assertNotIn("Cause:", released)


if __name__ == "__main__":
    unittest.main()
