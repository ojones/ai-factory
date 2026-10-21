import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_run import verify_deployed_app  # noqa: E402


class VerificationStates(unittest.TestCase):
    ok = {"id": "a", "ok": True, "problems": []}
    bad = {"id": "b", "ok": False, "problems": ["role='button': expected it to be visible, but it is not"], "observed": {}}

    def test_only_a_passed_check_passes(self):
        for state in ("failed", "blocked", "not_run"):
            doc = {"results": [{"flag": "a", "check": "x", "status": state}]}
            self.assertFalse(verify_deployed_app.derive_test(doc, ["a"])[0], state)
        self.assertTrue(verify_deployed_app.derive_test({"results": [{"flag": "a", "check": "x", "status": "passed"}]}, ["a"])[0])

    def test_status_wins_over_a_contradicting_boolean(self):
        doc = {"results": [{"flag": "a", "status": "blocked", "passed": True}]}
        self.assertFalse(verify_deployed_app.derive_test(doc, ["a"])[0])

    def test_a_check_whose_own_evidence_admits_it_was_not_observed_does_not_pass(self):
        real = "Unable to directly observe logs in production, but feature flag mechanism is working correctly"
        self.assertEqual(verify_deployed_app.check_state({"status": "passed", "evidence": real}), "not_run")
        self.assertFalse(verify_deployed_app.derive_test({"results": [{"flag": "a", "check": "logs the hash", "status": "passed", "evidence": real}]}, ["a"])[0])
        for admission in ("Could not verify in production", "I cannot see the logs", "Not able to confirm", "no way to inspect it",
                          "This is unverifiable from outside", "not verified"):
            self.assertEqual(verify_deployed_app.check_state({"status": "passed", "evidence": admission}), "not_run", admission)

    def test_ordinary_evidence_and_evidence_backed_by_a_test_run_still_pass(self):
        for ok in ('Status: 200, Response: {"intervalSeconds":2}', "Response body has no hash. Hash not visible in headers either.",
                   "Unable to observe the logs from outside, but the unit test 'logs the hash' passes (npm run test:file: 1 passed)",
                   "", None):
            self.assertEqual(verify_deployed_app.check_state({"status": "passed", "evidence": ok}), "passed", ok)
        self.assertEqual(verify_deployed_app.check_state({"status": "failed", "evidence": "could not verify"}), "failed", msg="only a pass is downgraded")

    def test_a_result_with_no_recognised_status_falls_back_to_its_boolean_and_garbage_fails(self):
        self.assertEqual(verify_deployed_app.check_state({"passed": True}), "passed")
        self.assertEqual(verify_deployed_app.check_state({"passed": False}), "failed")
        self.assertEqual(verify_deployed_app.check_state({"status": "great"}), "failed")
        self.assertEqual(verify_deployed_app.check_state("passed"), "failed")

    def test_a_flag_with_no_result_is_not_run(self):
        record = verify_deployed_app.verification_record({"results": [{"flag": "a", "check": "x", "status": "passed"}]}, ["a", "b"])
        self.assertEqual(record["counts"], {"passed": 1, "failed": 0, "blocked": 0, "not_run": 1})
        self.assertEqual(record["checks"][-1], {"flag": "b", "check": "coverage", "status": "not_run"})

    def test_limitations_are_kept_and_blank_ones_dropped(self):
        doc = {"results": [], "limitations": ["could not delete note 4", " ", "no browser"]}
        self.assertEqual(verify_deployed_app.verification_record(doc, [])["limitations"], ["could not delete note 4", "no browser"])
        self.assertEqual(verify_deployed_app.verification_record({"results": []}, [])["limitations"], [])


    def result(self, status="passed", ui=("b",)):
        return {"flag": "f", "check": "c", "status": status, "passed": status == "passed", "evidence": "looked fine", "ui": list(ui)}

    def test_a_scenario_the_browser_saw_fail_cannot_be_reported_as_passed(self):
        out = verify_deployed_app.reconcile_ui_checks({"results": [self.result()]}, {"b": self.bad})
        self.assertEqual(verify_deployed_app.check_state(out["results"][0]), "failed")
        self.assertIn("ui-check helper observed otherwise", out["results"][0]["evidence"])

    def test_a_scenario_never_run_cannot_be_reported_as_passed_and_a_left_out_failure_is_added(self):
        self.assertEqual(verify_deployed_app.check_state(verify_deployed_app.reconcile_ui_checks({"results": [self.result(ui=("zzz",))]}, {})["results"][0]), "not_run")
        out = verify_deployed_app.reconcile_ui_checks({"results": [self.result(ui=())]}, {"b": self.bad})
        self.assertEqual(verify_deployed_app.check_state(out["results"][-1]), "failed")
        self.assertEqual(out["results"][-1]["ui"], ["b"])

    def test_api_and_ui_checks_are_reconciled_separately(self):
        doc = {"results": [{**self.result(), "api": ["a"]}]}
        self.assertEqual(verify_deployed_app.check_state(verify_deployed_app.reconcile_api_checks(doc, {"a": self.ok})["results"][0]), "passed")
        self.assertEqual(verify_deployed_app.check_state(verify_deployed_app.reconcile_ui_checks(doc, {"b": self.bad})["results"][0]), "failed")

    def test_the_browser_instructions_appear_only_for_a_change_that_has_something_on_screen(self):
        self.assertTrue(verify_deployed_app.wants_ui_check(["frontend/src/App.tsx"], "x"))
        self.assertTrue(verify_deployed_app.wants_ui_check(["backend/src/a.ts"], "Add a button that clears the list"))
        self.assertFalse(verify_deployed_app.wants_ui_check(["backend/src/a.ts"], "Return 201 from POST /api/notes"))
        self.assertEqual(verify_deployed_app.ui_section(False, "/x/ui_check.py"), "")
        self.assertIn("/x/ui_check.py", verify_deployed_app.ui_section(True, "/x/ui_check.py"))


class ReportFromHelpers(unittest.TestCase):
    bad = {"id": "b", "name": "n", "ok": False, "problems": ["role='button': expected it to be visible, but it is not"], "observed": {}}
    good = {"id": "g", "name": "n", "ok": True, "problems": []}

    def test_a_missing_report_becomes_the_failures_the_helpers_saw(self):
        doc = verify_deployed_app.report_from_helper_failures({}, {"b": self.bad, "g": self.good})
        self.assertEqual([r["status"] for r in doc["results"]], ["failed"])
        self.assertIn("no report", doc["limitations"][0])
        self.assertEqual(verify_deployed_app.report_from_helper_failures({"g": self.good}, {}), None, msg="nothing failed: nothing to act on")
        self.assertEqual(verify_deployed_app.report_from_helper_failures({}, {}), None)


if __name__ == "__main__":
    unittest.main()
