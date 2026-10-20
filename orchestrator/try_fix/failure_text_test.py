import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import failure_text  # noqa: E402

FACTS = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass", "run_url": "https://x/run/9",
         "issue_number": "66", "review_passes": 4, "spent_usd": 0.61, "cap_usd": 0.75, "commits": ["a", "b"],
         "final_blocking": ["the change is not behind the flag the spec names", "put still 404s while that flag is off"],
         "recurring_findings": ["flag the spec names"]}
REVERT = {"status": "rolled_back", "restored": "0123456789ab", "deploy": "healthy"}
RESULT = {"category": "plan_gap", "root_cause": "The planner invented a flag to retire a flag.", "change_summary": "Planner prompt: retiring is internal",
          "requirements": ["The planner marks retirement change sets internal_only"]}


class Requirements(unittest.TestCase):
    def test_the_requirements_are_numbered_checkable_and_end_with_a_rerun(self):
        reqs = failure_text.requirements(FACTS, RESULT, REVERT)
        self.assertIn("Confirm the app behaves exactly as before", reqs[0])
        self.assertTrue(any("within the configured review rounds" in r and "not behind the flag" in r for r in reqs))
        self.assertIn("The planner marks retirement change sets internal_only", reqs)
        self.assertIn("ends `released` or `nothing_to_release`", reqs[-1])

    def test_every_outcome_gets_a_requirement_of_its_own(self):
        for outcome, needle in (("budget_exhausted", "cost cap"), ("time_limit", "time limit"), ("crash", "no longer crashes"),
                                ("watchdog_disabled", "regression the watchdog found"), ("needs_human", "resolved")):
            text = " ".join(failure_text.requirements(dict(FACTS, outcome=outcome), None, REVERT))
            self.assertIn(needle, text, outcome)

    def test_a_failed_rollback_is_the_first_requirement_and_said_plainly(self):
        failed = {"status": "failed", "reason": "could not start rollback-fly.yml"}
        self.assertIn("rollback failed", failure_text.requirements(FACTS, RESULT, failed)[0])
        self.assertIn("**The automatic rollback failed**", failure_text.rollback_line(failed))
        self.assertIn("run `rollback-fly.yml`", failure_text.rollback_line(failed))
        regression = dict(FACTS, outcome="regression")
        self.assertIn("no rollback was done", failure_text.requirements(regression, RESULT, {"status": "skipped", "reason": "switched off"})[0])
        self.assertEqual(failure_text.rollback_line(None), "No rollback was attempted.")
        self.assertIn("Nothing was reverted in git", failure_text.rollback_line(REVERT))

    def test_a_regression_is_fixed_forward(self):
        text = " ".join(failure_text.requirements(dict(FACTS, outcome="regression", message="old route broke"), None, REVERT))
        self.assertIn("fix it forward", text)

    def test_bugs_the_tester_saw_are_requirements(self):
        bugs = [{"kind": "dark", "flag": "pin", "check": "pin route answers 201", "evidence": "got 500", "repro": "curl -X POST /api/pins"}]
        text = " ".join(failure_text.requirements(dict(FACTS, bugs=bugs), None, None))
        self.assertIn("Fix this bug the tester saw (the new change, still dark): pin route answers 201", text)
        self.assertIn("Repro: curl -X POST /api/pins", text)

    def test_a_missing_flag_asks_for_the_flag_the_task_names_and_says_nothing_was_rolled_back(self):
        facts = {"outcome": "flag_missing", "message": "Not released: `x` ...", "flag_notes": [{"slug": "x", "kind": "missing_dark", "guess": "g"}], "commits": ["h"]}
        reqs = failure_text.requirements(facts, None, None)
        self.assertTrue(any("exists in GrowthBook" in r and "`x`" in r and "Nothing was rolled back" in r for r in reqs))

    def test_the_apps_side_carries_no_requirements_about_fixing_the_factory(self):
        result = dict(RESULT, category="model_limit", requirements=["The tester agent must produce a valid JSON test report"])
        self.assertNotIn("tester agent must produce", " ".join(failure_text.requirements(FACTS, result, REVERT, app_side=True)))
        self.assertIn("tester agent must produce", " ".join(failure_text.requirements(FACTS, result, REVERT)))


class Render(unittest.TestCase):
    def test_the_issue_explains_what_happened_what_was_done_and_what_happens_next(self):
        body = failure_text.render(FACTS, RESULT, REVERT, "factory", "https://github.com/o/f/issues/66")
        for needle in ("## What happened", "ended **round_limit**", "https://x/run/9", "Still blocking at the end: the change is not behind",
                       "## What was done automatically", "the deploy is **healthy**", "## Analysis (automated, and may be wrong)",
                       "**plan_gap**", "invented a flag", "## Requirements", "1. ", "starts again by itself"):
            self.assertIn(needle, body, needle)
        self.assertIn("did not name a cause", failure_text.render(FACTS, None, REVERT, "info"))
        self.assertIn("nothing runs until", failure_text.render(FACTS, None, REVERT, "info"))
        self.assertNotIn("ready-for-staging", body)


if __name__ == "__main__":
    unittest.main()
