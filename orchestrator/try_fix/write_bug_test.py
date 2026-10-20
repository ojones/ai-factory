import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config, spend_budget  # noqa: E402

from try_fix import event, write_bug  # noqa: E402

CFG = {**config.load(), "limits": {**config.load()["limits"], "planner_max_criteria": 6}}
EV = event.make("build_run", "failure", "demo", "round limit reached", "fp", story=7)
VERDICT = {"key": EV["key"], "verdict": "fix", "target": "managed_app", "cause": "spec_ambiguity", "reason": "a failure is always fixed", "event": EV}
FACTS = {"app": "demo", "outcome": "round_limit", "message": "out of rounds", "run_url": "https://x/run/1", "issue_number": "7",
         "final_blocking": ["todos accept blank text"], "recurring_findings": [], "bugs": [], "flag_notes": [], "commits": []}
GOOD = {"how_found": "Build Run 1 stopped at the round limit.", "root_cause": "Blank text is accepted, so review kept failing.",
        "what_it_takes": ["Blank text is rejected"], "requirements": ["POST /api/todos with blank text answers 400", "A test covers blank text"]}


class Write(unittest.TestCase):
    def test_a_valid_answer_is_used_and_marked_as_the_agents(self):
        got = write_bug.write(VERDICT, FACTS, None, CFG, "k", lambda *a, **k: GOOD)
        self.assertEqual((got["source"], got["requirements"]), ("agent", GOOD["requirements"]))

    def test_the_prompt_carries_the_decision_and_the_evidence_but_not_a_credential(self):
        seen = []
        write_bug.write(VERDICT, FACTS, None, CFG, "the-agents-key", lambda base, key, model, system, user, **kw: seen.append((key, model, user)) or GOOD)
        key, model, user = seen[0]
        self.assertEqual((key, model), ("the-agents-key", CFG["roles"]["try_fix"]["model"]))
        self.assertIn("spec_ambiguity", user)
        self.assertIn("todos accept blank text", user)
        for secret_env in ("FACTORY_PAT", "DEEPINFRA_API_KEY"):
            self.assertNotIn(secret_env, user)

    def test_an_unusable_answer_or_a_failed_call_falls_back_to_the_orchestrators_text(self):
        for ask in (lambda *a, **k: {"how_found": "x"}, mock.Mock(side_effect=RuntimeError("down")), lambda *a, **k: ["no"]):
            got = write_bug.write(VERDICT, FACTS, None, CFG, "k", ask)
            self.assertEqual(got["source"], "fallback")
            self.assertTrue(got["requirements"] and got["how_found"] and got["root_cause"])

    def test_no_key_or_no_role_asks_nothing(self):
        ask = mock.Mock()
        self.assertEqual(write_bug.write(VERDICT, FACTS, None, CFG, None, ask)["source"], "fallback")
        no_role = {**CFG, "roles": {k: v for k, v in CFG["roles"].items() if k != "try_fix"}}
        self.assertEqual(write_bug.write(VERDICT, FACTS, None, no_role, "k", ask)["source"], "fallback")
        ask.assert_not_called()

    def test_a_secret_in_the_evidence_never_reaches_the_model_or_the_fallback(self):
        token = "ghp_" + "a1" * 15
        leaky = {**VERDICT, "event": {**EV, "evidence": f"log line with {token}"}}
        seen = []
        write_bug.write(leaky, FACTS, None, CFG, "k", lambda *a, **k: seen.append(a[4]) or GOOD)
        self.assertNotIn("a1a1", seen[0])
        plain = write_bug.write(leaky, FACTS, None, CFG, None)
        self.assertNotIn("a1a1", str(plain))


class Fallback(unittest.TestCase):
    def test_a_failed_run_gets_the_requirements_failure_text_already_writes_and_keeps_the_last_one_within_the_cap(self):
        got = write_bug.fallback(VERDICT, FACTS, None, 2)
        self.assertEqual(len(got["requirements"]), 2)
        self.assertIn("A re-run of the same request", got["requirements"][-1])
        self.assertIn("spec_ambiguity", got["root_cause"])
        self.assertIn("https://x/run/1", got["how_found"])

    def test_an_event_with_no_run_gets_a_fix_and_a_test_requirement_and_no_cause_says_so(self):
        scan = event.make("production_feedback", "failure", "demo", "TypeError in /api/todos", "fp2", evidence="3 times in 6h")
        got = write_bug.fallback({"key": scan["key"], "target": "managed_app", "cause": None, "reason": "seen 3 times", "event": scan})
        self.assertEqual(len(got["requirements"]), 2)
        self.assertTrue(got["root_cause"].startswith("No cause was named."))
        self.assertIn("a scan of the deployed app's logs", got["how_found"])

    def test_the_fallback_passes_its_own_validation(self):
        from try_fix import validate_bug
        got = write_bug.fallback(VERDICT, FACTS, None, 6)
        self.assertEqual(validate_bug.check(got, 6)[1], [])


class Mint(unittest.TestCase):
    def test_the_credential_is_limited_to_the_try_fix_cap_and_its_own_model(self):
        made = {}

        class Budget:
            def __init__(self, key, cap, ttl):
                made.update(key=key, cap=cap)

            def mint(self, model):
                made["model"] = model
                return "jwt"
        with mock.patch.object(spend_budget, "Budget", Budget):
            key, _ = write_bug.mint(CFG, "parent")
        self.assertEqual((key, made["key"], made["cap"], made["model"]), ("jwt", "parent", float(CFG["limits"]["try_fix_cost_cap_usd"]), CFG["roles"]["try_fix"]["model"]))

    def test_a_failure_to_mint_gives_none_and_never_raises(self):
        with mock.patch.object(spend_budget, "Budget", side_effect=RuntimeError("no")):
            self.assertEqual(write_bug.mint(CFG, "parent"), (None, None))


if __name__ == "__main__":
    unittest.main()
