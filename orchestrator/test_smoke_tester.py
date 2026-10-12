"""The pure logic of agents/smoke-tester/run.py: how a bug is seeded and how a tester report is judged."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
spec = importlib.util.spec_from_file_location("smoke_tester", ROOT / "agents" / "smoke-tester" / "run.py")
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)

DATA = st.load()
BY = {f["id"]: f for f in DATA["fixtures"]}


def report(*checks):
    return {"results": [{"flag": "notes-api", "check": c, "status": s, "evidence": e} for c, s, e in checks], "limitations": []}


class Seeding(unittest.TestCase):
    def test_every_fixture_edit_applies_exactly_once_to_the_base_feature(self):
        source = (ROOT / "agents" / "smoke-tester" / "base" / "notes.ts").read_text()
        for fixture in DATA["fixtures"]:
            mutated = st.apply_edits(source, fixture["edits"])
            self.assertEqual(mutated == source, not fixture["edits"], fixture["id"])  # only the correct feature is unchanged

    def test_an_edit_that_does_not_apply_is_an_error_not_a_silent_correct_app(self):
        with self.assertRaises(ValueError):
            st.apply_edits("a b", [["zzz", "y"]])
        with self.assertRaises(ValueError):
            st.apply_edits("a a", [["a", "b"]])  # ambiguous

    def test_the_unobservable_requirement_is_only_in_that_fixtures_spec(self):
        plain, hidden = st.spec_for(DATA, BY["good"]), st.spec_for(DATA, BY["unobservable"])
        self.assertNotIn("audit log", plain)
        self.assertIn("audit log", hidden)

    def test_fixtures_declare_what_they_expect_and_how_to_recognise_the_bug(self):
        self.assertEqual(sum(f["expect"] == "pass" for f in DATA["fixtures"]), 1)
        for f in DATA["fixtures"]:
            self.assertIn(f["expect"], ("pass", "fail", "not_pass"))
            if f["expect"] != "pass":
                self.assertTrue(f.get("match"), f["id"])


class Judging(unittest.TestCase):
    flag = DATA["flag"]

    def test_a_correct_app_that_passes_is_correct_and_one_that_fails_is_a_false_alarm(self):
        ok = report(("create", "passed", "201"))
        self.assertEqual(st.judge(BY["good"], ok, self.flag)["outcome"], "correct")
        bad = report(("create", "failed", "got 500"))
        self.assertEqual(st.judge(BY["good"], bad, self.flag)["outcome"], "false_alarm")

    def test_a_buggy_app_that_passes_is_missed_and_one_that_fails_is_caught(self):
        self.assertEqual(st.judge(BY["wrong-status"], report(("create", "passed", "201")), self.flag)["outcome"], "missed")
        caught = st.judge(BY["wrong-status"], report(("POST returns 201", "failed", "status was 200")), self.flag)
        self.assertEqual((caught["outcome"], caught["right_reason"]), ("caught", True))

    def test_the_reason_patterns_do_not_match_unrelated_digits_or_words(self):
        # id-zero used "0|zero|...", which matched the 0 in "200"; dup-ids used "...|id", which matched every message.
        unrelated = "Health check endpoint returns 200 | Unable to test due to environment constraints for id lookups"
        for fid in ("id-zero", "dup-ids", "lenient-id", "wrong-status", "no-trim", "no-blank-check"):
            import re as _re
            self.assertIsNone(_re.search(BY[fid]["match"], unrelated, _re.I), fid)
        self.assertTrue(__import__("re").search(BY["id-zero"]["match"], "GET /api/notes/0 returned 404, expected 400", __import__("re").I))
        self.assertTrue(__import__("re").search(BY["dup-ids"]["match"], "All notes receive ID=1 instead of unique IDs", __import__("re").I))

    def test_caught_for_the_wrong_reason_is_told_apart(self):
        wrong = st.judge(BY["wrong-status"], report(("health", "failed", "connection refused")), self.flag)
        self.assertEqual((wrong["outcome"], wrong["right_reason"]), ("caught", False))

    def test_a_check_that_admits_it_was_not_observed_does_not_count_as_a_pass(self):
        # the integrity rule: this is how the unobservable requirement was wrongly released once
        doc = report(("every created note is written to the audit log", "passed", "Unable to directly observe logs in production"))
        self.assertEqual(st.judge(BY["unobservable"], doc, self.flag)["outcome"], "caught")
        honest = report(("every created note is written to the audit log", "passed", "unit test asserts it: npm run test:file passed"))
        self.assertEqual(st.judge(BY["unobservable"], honest, self.flag)["outcome"], "missed")

    def test_a_flag_with_no_result_cannot_pass_and_finds_nothing(self):
        self.assertEqual(st.judge(BY["wrong-order"], {"results": []}, self.flag)["outcome"], "inconclusive")

    def test_a_tester_that_could_not_run_anything_is_inconclusive_not_a_catch(self):
        # Seen live: every check not_run ("unable to execute curl"). The release gate refuses it, but it found no bug.
        nothing_ran = report(("health", "not_run", "Unable to test due to environment constraints"), ("create", "not_run", "same"))
        for fid in ("wrong-status", "good"):
            self.assertEqual(st.judge(BY[fid], nothing_ran, self.flag)["outcome"], "inconclusive", fid)
        # one real failure alongside not_run checks is a real catch
        mixed = report(("health", "not_run", "x"), ("create", "failed", "got 200"))
        self.assertEqual(st.judge(BY["wrong-status"], mixed, self.flag)["outcome"], "caught")
        # the unobservable fixture expects "not passed", and not_run is exactly the honest answer there
        honest = report(("audit log line", "not_run", "cannot see logs"))
        self.assertEqual(st.judge(BY["unobservable"], honest, self.flag)["outcome"], "caught")

    def test_a_report_that_is_missing_or_unreadable_is_unusable_not_a_catch(self):
        self.assertEqual(st.judge(BY["wrong-status"], None, self.flag)["outcome"], "unusable")
        self.assertEqual(st.judge(BY["wrong-status"], {"nope": 1}, self.flag)["outcome"], "unusable")


class Summary(unittest.TestCase):
    def test_inconclusive_runs_are_left_out_of_the_detection_rate_and_counted_separately(self):
        results = [{"fixture": "wrong-status", "outcome": "caught", "right_reason": True, "cost": 0},
                   {"fixture": "wrong-status", "outcome": "inconclusive", "right_reason": None, "cost": 0},
                   {"fixture": "wrong-order", "outcome": "missed", "right_reason": None, "cost": 0}]
        s = st.summarize(results, DATA["fixtures"])
        self.assertEqual((s["detection_rate"], s["inconclusive_runs"]), (0.5, 1))

    def test_rates_are_over_the_buggy_runs_and_false_alarms_over_the_correct_ones(self):
        results = [{"fixture": "good", "outcome": "correct", "cost": 0.05}, {"fixture": "good", "outcome": "false_alarm", "cost": 0.05},
                   {"fixture": "wrong-status", "outcome": "caught", "right_reason": True, "cost": 0.05},
                   {"fixture": "wrong-status", "outcome": "missed", "right_reason": None, "cost": 0.05},
                   {"fixture": "wrong-order", "outcome": "caught", "right_reason": False, "cost": 0.05},
                   {"fixture": "wrong-order", "outcome": "caught", "right_reason": True, "cost": 0.05}]
        s = st.summarize(results, DATA["fixtures"])
        self.assertEqual((s["detection_rate"], s["right_reason_rate"], s["false_alarm_rate"]), (0.75, 0.5, 0.5))
        self.assertAlmostEqual(s["cost"], 0.30)
        self.assertEqual([r["fixture"] for r in s["rows"]], ["good", "wrong-status", "wrong-order"])


if __name__ == "__main__":
    unittest.main()
