import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from try_fix import collect_events  # noqa: E402


def facts(**kw):
    return {"app": "demo", "outcome": "released", "message": "Released 1 flag(s).", "run_url": "https://x/run/1", "issue_number": "66",
            "flags": ["issue-66"], "bugs": [], "unverified": [], "final_minor": [], "improvements": [], "flag_notes": [], **kw}


class FromRun(unittest.TestCase):
    def test_a_clean_release_has_no_events(self):
        self.assertEqual(collect_events.from_run(facts(), "fp"), [])

    def test_the_ending_of_a_failed_run_is_one_failure_event_and_a_watchdog_switch_off_is_dark(self):
        got = collect_events.from_run(facts(outcome="round_limit", message="out of rounds"), "fp")
        self.assertEqual([(e["severity"], e["source"], e["story"], e["released"]) for e in got], [("failure", "build_run", 66, False)])
        dog = collect_events.from_run(facts(outcome="watchdog_disabled", message="errors rose"), "fp")
        self.assertEqual((dog[0]["source"], dog[0]["released"], dog[0]["flag"]), ("watchdog", False, "issue-66"))

    def test_answers_and_a_provider_with_no_balance_are_not_failures_to_fix(self):
        for outcome in ("refused", "awaiting_secret", "provider_blocked", "nothing_to_release"):
            self.assertEqual(collect_events.from_run(facts(outcome=outcome), "fp"), [], outcome)

    def test_the_warnings_a_good_run_leaves_behind_become_warning_events(self):
        got = collect_events.from_run(facts(
            bugs=[{"kind": "dark", "check": "empty text rejected", "flag": "issue-66", "evidence": "201"}],
            unverified=[{"check": "ui loads", "state": "not_run"}],
            final_minor=[{"summary": "unused import", "evidence": "a.ts"}],
            improvements=[{"source": "tester", "target": "managed_app", "summary": "add a test", "evidence": ""},
                          {"source": "reviewer", "target": "factory", "summary": "prompt gap", "evidence": ""}],
            flag_notes=[{"slug": "issue-66", "kind": "live_without_flag", "guess": "never read"}]), "fp")
        self.assertEqual([e["source"] for e in got], ["tester", "tester", "reviewer", "tester", "build_run"])
        self.assertTrue(all(e["severity"] == "warning" and e["released"] is True for e in got))
        self.assertNotIn("prompt gap", [e["summary"] for e in got], "a Factory improvement stays a factory-learning record")

    def test_the_tester_bugs_of_a_failed_run_are_part_of_its_failure_not_separate_events(self):
        got = collect_events.from_run(facts(outcome="regression", bugs=[{"kind": "regression", "check": "list works", "evidence": "500"}]), "fp")
        self.assertEqual([e["severity"] for e in got], ["failure"])

    def test_warnings_are_capped_and_the_failure_comes_first(self):
        many = [{"summary": f"m{n}", "evidence": ""} for n in range(20)]
        got = collect_events.from_run(facts(outcome="round_limit", message="no progress", final_minor=many), "fp")
        self.assertEqual(got[0]["severity"], "failure")
        self.assertEqual(len(got), 1 + collect_events.MAX_WARNINGS)


if __name__ == "__main__":
    unittest.main()
