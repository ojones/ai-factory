import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import lesson_records, run_summary  # noqa: E402
from retrospective import run_audit as audit


def good_run(**kw):
    d = {"outcome": "released", "cap_usd": 2.0, "spent_usd": 0.6, "head_sha": "abc", "build_kind": "update", "commits": ["abc"],
         "blocking": [], "release": {"released": ["x.feature.a"], "kept": []},
         "verification": {"round": 1, "sha": "abc", "checks": [], "limitations": [],
                          "counts": {"passed": 3, "failed": 0, "blocked": 0, "not_run": 0}},
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2},
                    {"stage": "Review", "round": 1, "verdict": "clean", "cost_usd": 0.05},
                    {"stage": "Test", "round": 1, "verdict": "passed", "cost_usd": 0.1},
                    {"stage": "Release", "round": "-", "verdict": "1 flag(s) released", "cost_usd": 0}]}
    d.update(kw)
    return d


def rules(d):
    return [p["rule"].split()[0] for p in audit.audit_report(d)]


class Audit(unittest.TestCase):
    def test_a_correct_released_run_breaks_nothing(self):
        self.assertEqual(audit.audit_report(good_run()), [])
        self.assertEqual(audit.render_audit([]), "")

    def test_spend_over_the_cap_beyond_one_call_is_flagged(self):
        self.assertEqual(rules(good_run(spent_usd=2.4)), [])
        self.assertEqual(rules(good_run(spent_usd=2.6)), ["INV-09"])

    def test_a_release_without_a_clean_review_or_passing_test_is_flagged(self):
        d = good_run()
        d["stages"][1]["verdict"] = "2 blocking"
        d["stages"][2]["verdict"] = "1 failed"
        self.assertEqual(rules(d), ["INV-03", "INV-03"])
        self.assertEqual(rules(good_run(stages=[])), ["INV-03", "INV-03"])

    def test_review_and_test_from_different_rounds_is_flagged(self):
        d = good_run()
        d["stages"][2]["round"] = 2
        self.assertEqual(rules(d), ["INV-03"])

    def test_a_release_with_a_check_that_did_not_pass_is_flagged(self):
        d = good_run()
        d["verification"]["counts"]["blocked"] = 1
        self.assertEqual(rules(d), ["INV-05"])

    def test_release_before_the_last_review_is_flagged(self):
        d = good_run()
        d["stages"] = [d["stages"][0], d["stages"][3], d["stages"][1], d["stages"][2]]
        self.assertEqual(rules(d), ["A-03"])

    def test_a_run_that_never_recorded_its_outcome_is_flagged_and_a_failed_run_is_not_held_to_release_rules(self):
        self.assertEqual(rules({"outcome": "running", "stages": []}), ["A-01"])
        self.assertEqual(rules({"outcome": "round_limit", "cap_usd": 2, "spent_usd": 1.0, "stages": [], "blocking": [{"summary": "x"}]}), [])

    def test_watchdog_disabled_with_nothing_released_is_flagged(self):
        self.assertEqual(rules({"outcome": "watchdog_disabled", "stages": []}), ["INV-07"])

    def test_an_ok_run_with_open_findings_or_an_update_with_no_commit_is_flagged(self):
        self.assertEqual(rules(good_run(blocking=[{"summary": "x"}])), ["A-04"])
        self.assertEqual(rules(good_run(commits=[])), ["A-05"])
        self.assertEqual(rules(good_run(commits=[], build_kind="first build")), [])

    def test_the_summary_lists_violations_and_the_post_mortem_records_them_as_a_severe_lesson(self):
        d = good_run(spent_usd=3.0)
        d.update(app="x", message="", review_passes=1, audit=audit.audit_report(d))
        for st in d["stages"]:
            st.setdefault("agent", "-")
        self.assertIn("Audit: 1 invariant(s) broken", run_summary.render_summary(d))
        facts = {"app": "x", "outcome": "released", "message": "", "run_url": "u", "issue_number": "1", "spent_usd": 3.0,
                 "cap_usd": 2.0, "review_passes": 1, "commits": [], "audit": d["audit"], "final_blocking": [], "rounds": [],
                 "recurring_findings": [], "stages": [], "final_minor": []}
        lessons = lesson_records.lessons_from(facts)
        self.assertEqual(lessons[0]["kind"], "audit_violation")
        self.assertTrue(lessons[0]["severe"])


if __name__ == "__main__":
    unittest.main()
