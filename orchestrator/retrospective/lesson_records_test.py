import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import lesson_records, run_facts  # noqa: E402

STATE = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass",
         "run_url": "http://run", "issue_number": "7", "spent_usd": 1.5, "commits": ["a"],
         "blocking": [{"summary": "The kill switch is mounted after the new route"}],
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2, "usage": {"seconds": 120, "calls": 30}},
                    {"stage": "Release", "round": "-", "verdict": "x", "cost_usd": 0, "usage": None}]}


def facts_for(**kw):
    base = {"app": "demo", "outcome": "released", "message": "ok", "run_url": "u", "issue_number": "7", "spent_usd": 0.3,
            "cap_usd": 2.0, "review_passes": 1, "commits": [], "final_blocking": [], "rounds": [], "recurring_findings": [],
            "stages": [], "final_minor": []}
    base.update(kw)
    return base


class Lessons(unittest.TestCase):
    def kinds(self, **kw):
        return [x["kind"] for x in lesson_records.lessons_from(facts_for(**kw))]

    def test_a_clean_quick_cheap_run_teaches_nothing(self):
        self.assertEqual(self.kinds(), [])

    def test_a_watchdog_disable_is_a_severe_lesson_and_comes_first(self):
        lessons = lesson_records.lessons_from(facts_for(outcome="watchdog_disabled", message="health check failed", spent_usd=1.9))
        self.assertEqual([x["kind"] for x in lessons], ["watchdog_disabled"])
        self.assertTrue(lessons[0]["severe"])
        both = lesson_records.lessons_from(facts_for(spent_usd=1.9, review_passes=3, outcome="released"))
        self.assertEqual({x["kind"] for x in both}, {"many_rounds", "budget_high"})

    def test_many_rounds_only_when_the_run_finished_ok(self):
        rounds = [{"round": i, "blocking": [f"kill switch missing {i}"], "tester_blocking": []} for i in (1, 2, 3)]
        self.assertEqual(self.kinds(review_passes=3, rounds=rounds), ["many_rounds"])
        self.assertEqual(self.kinds(review_passes=3, rounds=rounds, outcome="round_limit"), [])
        self.assertEqual(self.kinds(review_passes=2, rounds=rounds), [])

    def test_a_first_pass_test_failure_is_a_lesson_with_a_stable_title(self):
        rounds = [{"round": 1, "blocking": ["a: create note"], "tester_blocking": ["a: create note"]},
                  {"round": 2, "blocking": [], "tester_blocking": []}]
        lessons = lesson_records.lessons_from(facts_for(review_passes=2, rounds=rounds))
        self.assertEqual([x["kind"] for x in lessons], ["first_pass_test_failure"])
        again = lesson_records.lessons_from(facts_for(review_passes=2, rounds=rounds, spent_usd=0.9, run_url="other"))
        self.assertEqual(lessons[0]["title"], again[0]["title"])

    def test_slow_stage_budget_and_cap_on_how_many_are_recorded(self):
        slow = [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.1, "seconds": 2000, "calls": 9}]
        self.assertEqual(self.kinds(stages=slow), ["slow_stage"])
        self.assertEqual(self.kinds(spent_usd=1.4), ["budget_high"])
        rounds = [{"round": 1, "blocking": ["x"], "tester_blocking": ["x"]}]
        many = lesson_records.lessons_from(facts_for(review_passes=4, spent_usd=1.9, stages=slow, rounds=rounds))
        self.assertEqual(len(many), lesson_records.MAX_LESSONS)  # four applied: many_rounds, first_pass_test_failure, budget_high, slow_stage

    def test_collect_facts_keeps_which_findings_came_from_the_tester(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "findings-1.json").write_text(json.dumps({"round": 1, "minor": [], "blocking": [
                {"source": "tester", "summary": "a: x"}, {"source": "reviewer", "summary": "no flag"}]}))
            facts = run_facts.collect_facts(tmp, dict(STATE, outcome="released", review_passes=2, cap_usd=2.0))
        self.assertEqual(facts["rounds"][0]["tester_blocking"], ["a: x"])
        self.assertEqual(facts["review_passes"], 2)


class OneEventOneRecord(unittest.TestCase):
    def test_a_watchdog_disable_is_one_lesson_not_two(self):
        self.assertFalse(lesson_records.records_stuck_issue("watchdog_disabled"))
        for stuck in ("round_limit", "stuck", "needs_human", "crash", "budget_exhausted", "time_limit"):
            self.assertTrue(lesson_records.records_stuck_issue(stuck), stuck)
        for ok in ("released", "nothing_to_release", "planned"):
            self.assertFalse(lesson_records.records_stuck_issue(ok), ok)


class FlagNotes(unittest.TestCase):
    def facts(self, notes, outcome="nothing_to_release"):
        return {"outcome": outcome, "message": "m", "rounds": [], "recurring_findings": [], "stages": [], "review_passes": 1, "flag_notes": notes}

    def test_a_missing_flag_note_becomes_one_lesson_with_its_kind_and_guess(self):
        note = {"slug": "x", "kind": "live_without_flag", "guess": "the coder added `x` besides the flag the Orchestrator created"}
        lessons = lesson_records.lessons_from(self.facts([note]))
        self.assertEqual([x["kind"] for x in lessons], ["flag_missing"])
        self.assertIn("live_without_flag", lessons[0]["detail"])
        self.assertIn("besides the flag", lessons[0]["detail"])
        self.assertTrue(lessons[0]["severe"])

    def test_a_dark_missing_flag_is_not_severe_and_a_run_without_notes_has_no_such_lesson(self):
        dark = {"slug": "x", "kind": "missing_dark", "guess": "g"}
        self.assertFalse(lesson_records.lessons_from(self.facts([dark], outcome="flag_missing"))[0]["severe"])
        self.assertEqual([x["kind"] for x in lesson_records.lessons_from(self.facts([]))], [])


if __name__ == "__main__":
    unittest.main()
