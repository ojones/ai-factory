# Tests for the model canary. Run: python3 -m unittest discover -p "*_test.py" orchestrator
import unittest

import yaml
from shared import config

from monitoring import canary as c

CFG = {"roles": {"coder": {"model": "a/new", "fallback_model": "b/old"}, "tester": {"model": "c/t"}, "planner": {"model": "p/x", "fallback_model": "p/y"}}}


class Drift(unittest.TestCase):
    def test_a_missing_primary_or_fallback_is_reported_by_role_and_kind(self):
        gone = {"a/new", "p/y"}
        found = c.drift(CFG, lambda m: "missing" if m in gone else "ok")
        self.assertEqual(found, [("coder", "a/new", "primary"), ("planner", "p/y", "fallback")])

    def test_unknown_answers_are_not_drift_and_nothing_missing_is_all_clear(self):
        self.assertEqual(c.drift(CFG, lambda m: "unknown"), [])
        self.assertIn("All 5 configured models answer", c.render([], 5))

    def test_the_issue_text_names_every_missing_model_and_what_a_run_does_about_it(self):
        text = c.render([("coder", "a/new", "primary")], 5)
        for needle in ("| coder | `a/new` | primary |", "fallback_model", "benchmark"):
            self.assertIn(needle, text)

    def test_the_shipped_profile_names_a_fallback_for_every_role_that_runs_an_agent(self):
        roles = yaml.safe_load((config.FACTORY_DIR / "agents" / "profiles.yml").read_text())["roles"]
        for role in ("coder", "tester", "reviewer", "planner"):
            self.assertTrue(roles[role].get("fallback_model"), role)
            self.assertNotEqual(roles[role]["fallback_model"], roles[role]["model"], role)


if __name__ == "__main__":
    unittest.main()
