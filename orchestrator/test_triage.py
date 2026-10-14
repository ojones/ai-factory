"""Tests for triage: secrets in public text and infeasible requests. Run: python3 -m unittest discover orchestrator"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import planner  # noqa: E402
import postmortem as pm  # noqa: E402
import triage as t  # noqa: E402


class Secrets(unittest.TestCase):
    def test_real_secret_shapes_are_found_and_never_repeated(self):
        text = "use ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2 and the key sk-" + "abcdefghijklmnopqrstuvwx for it"
        kinds = t.find_secrets(text)
        self.assertEqual(kinds, ["a GitHub token", "an API key (sk- style)"])
        message = t.secret_refusal(kinds)
        self.assertNotIn("ghp_a1B2", message)
        self.assertIn("rotate or revoke", message)
        self.assertEqual(t.find_secrets("-----BEGIN RSA PRIVATE KEY-----\nabc"), ["a private key"])
        self.assertEqual(t.find_secrets("password = hunter2hunter2"), ["a password or secret assignment"])

    def test_ordinary_sentences_and_placeholders_are_not_refused(self):
        for text in ("Add a password field to the login form", "The API key is read from the environment", "api_key = <your key here>",
                     "secret: ${SECRET}", "token: changeme", "Add a todo list with due dates"):
            self.assertEqual(t.find_secrets(text), [], text)


class Feasibility(unittest.TestCase):
    def test_a_blocked_plan_is_read_with_its_reasons_and_a_default_way_forward(self):
        plan = {"feasibility": {"status": "blocked", "category": "payments", "reasons": ["It asks to charge a card with Stripe."]}}
        blocked, category, reasons, possible = t.feasibility(plan)
        self.assertEqual((blocked, category, reasons), (True, "payments", ["It asks to charge a card with Stripe."]))
        self.assertIn("payment provider", possible)
        text = t.refusal_text(category, reasons, possible)
        self.assertIn("Nothing was built", text)
        self.assertIn("proceed-with-change", text)

    def test_an_ok_missing_or_malformed_feasibility_is_not_a_refusal(self):
        for plan in ({}, {"feasibility": {"status": "ok"}}, {"feasibility": "blocked"}, None, {"feasibility": {"status": "BLOCKED"}}):
            self.assertFalse(t.feasibility(plan)[0], plan)
        self.assertEqual(t.feasibility({"feasibility": {"status": "blocked", "category": "weird", "reasons": ["x"]}})[1], "outside_stack")

    def test_the_validator_accepts_a_refusal_without_change_sets_but_wants_a_reason(self):
        ok = {"feasibility": {"status": "blocked", "category": "secrets", "reasons": ["needs a Twilio key"]}}
        self.assertEqual(planner.validate_plan(ok), ([], []))
        self.assertTrue(planner.validate_plan({"feasibility": {"status": "blocked", "category": "secrets"}})[0])


class GoldenIntakes(unittest.TestCase):
    def test_the_good_examples_contain_no_secret_and_every_example_is_a_quoted_request(self):
        text = (b.FACTORY_DIR / "docs" / "golden-intakes.md").read_text()
        quotes = [l[2:] for l in text.splitlines() if l.startswith("> ")]
        self.assertGreaterEqual(len(quotes), 6)
        good = text.split("## Refused: payments")[0]
        self.assertEqual(t.find_secrets(good), [])


class Ending(unittest.TestCase):
    def test_a_refusal_is_not_a_failure_to_retry_or_learn_from(self):
        self.assertFalse(pm.wants_fix_request({"outcome": "refused"}, {}))
        self.assertFalse(pm.records_stuck_issue("refused"))
        self.assertNotIn("refused", b.OK_OUTCOMES)
        self.assertIn("refused", b.OUTCOME_TITLES)
        self.assertTrue(issubclass(b.Refused, Exception))


if __name__ == "__main__":
    unittest.main()
