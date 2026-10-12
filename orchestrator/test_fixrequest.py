import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_run as b  # noqa: E402
import fixrequest as fr  # noqa: E402
import update_intake as u  # noqa: E402

FACTS = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass", "run_url": "https://x/run/9",
         "issue_number": "66", "review_passes": 4, "spent_usd": 0.61, "cap_usd": 0.75, "commits": ["a", "b"],
         "final_blocking": ["the change is not behind the flag the spec names", "put still 404s while that flag is off"],
         "recurring_findings": ["flag the spec names"]}
REVERT = {"status": "reverted", "sha": "abcdef123456", "restored": "0123456789ab", "deploy": "healthy", "mode": "all"}
RESULT = {"category": "plan_gap", "root_cause": "The planner invented a flag to retire a flag.", "change_summary": "Planner prompt: retiring is internal",
          "requirements": ["The planner marks retirement change sets internal_only"]}


class Routing(unittest.TestCase):
    def test_the_cause_decides_where_it_goes(self):
        for c in ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap"):
            self.assertEqual(fr.route(c), "factory", c)
        for c in ("spec_ambiguity", "model_limit"):
            self.assertEqual(fr.route(c), "app", c)
        for c in ("infra", "unknown", None, "nonsense"):
            self.assertEqual(fr.route(c), "info", c)

    def test_one_fingerprint_per_app_intake_and_route(self):
        a = fr.fingerprint("demo", "66", "factory")
        self.assertEqual(a, fr.fingerprint("demo", "66", "factory"))
        self.assertNotEqual(a, fr.fingerprint("demo", "66", "app"))
        self.assertNotEqual(a, fr.fingerprint("demo", "67", "factory"))


class Content(unittest.TestCase):
    def test_the_requirements_are_numbered_checkable_and_end_with_a_rerun(self):
        reqs = fr.requirements(FACTS, RESULT, REVERT)
        self.assertIn("Confirm the app behaves exactly as before", reqs[0])
        self.assertTrue(any("within the configured review rounds" in r and "not behind the flag" in r for r in reqs))
        self.assertIn("The planner marks retirement change sets internal_only", reqs)
        self.assertIn("ends `released` or `nothing_to_release`", reqs[-1])

    def test_every_outcome_gets_a_requirement_of_its_own(self):
        for outcome, needle in (("budget_exhausted", "cost cap"), ("time_limit", "time limit"), ("crash", "no longer crashes"),
                                ("watchdog_disabled", "regression the watchdog found"), ("needs_human", "resolved")):
            text = " ".join(fr.requirements(dict(FACTS, outcome=outcome), None, REVERT))
            self.assertIn(needle, text, outcome)

    def test_a_failed_revert_is_the_first_requirement_and_said_plainly(self):
        failed = {"status": "failed", "reason": "RuntimeError: push rejected"}
        self.assertIn("revert failed", fr.requirements(FACTS, RESULT, failed)[0])
        self.assertIn("**The automatic revert failed**", fr.revert_line(failed))
        self.assertIn("were not reverted", fr.requirements(FACTS, RESULT, {"status": "skipped", "reason": "main moved on"})[0])
        self.assertEqual(fr.revert_line(None), "No revert was attempted.")

    def test_the_issue_explains_what_happened_what_was_done_and_what_to_do_next(self):
        body = fr.render(FACTS, RESULT, REVERT, "factory", "https://github.com/o/f/issues/66")
        for needle in ("## What happened", "ended **round_limit**", "https://x/run/9", "Still blocking at the end: the change is not behind",
                       "## What was done automatically", "the deploy of that commit is **healthy**", "## Analysis (automated, and may be wrong)",
                       "**plan_gap**", "invented a flag", "## Requirements", "1. ", "ready-for-factory-run"):
            self.assertIn(needle, body, needle)
        self.assertIn("proceed-with-change", fr.render(FACTS, RESULT, REVERT, "app"))
        self.assertIn("did not name a cause", fr.render(FACTS, None, REVERT, "info"))

    def test_the_app_request_carries_the_original_and_the_requirements_and_parses_as_a_form(self):
        text = fr.app_request(FACTS, RESULT, REVERT, "Retire the flag foo.")
        for needle in ("did not complete", "round_limit", "Retire the flag foo.", "Requirements for this attempt:"):
            self.assertIn(needle, text)
        self.assertNotIn("invented a flag", text)  # a Factory-side cause is not the app request's business
        issue = fr.render(FACTS, RESULT, REVERT, "app") + "\n---\n\n" + fr.intake_form("demo", text)
        self.assertEqual(u.app_name(issue), "demo")
        self.assertEqual(b.parse_intake(issue, 2.0, 10.0)[0], text)
        self.assertEqual(b.parse_intake(issue, 2.0, 10.0)[1], 2.0)  # the explanation did not leak into the cost-cap field


class Inference(unittest.TestCase):
    def test_a_run_that_ran_out_of_money_or_time_was_too_big_for_its_limits(self):
        for outcome in ("budget_exhausted", "time_limit"):
            self.assertEqual(fr.route(fr.inferred_category(None, outcome)), "app", outcome)
        for outcome in ("round_limit", "needs_human", "crash", "stuck"):
            self.assertEqual(fr.route(fr.inferred_category(None, outcome)), "info", outcome)
        self.assertEqual(fr.inferred_category("plan_gap", "budget_exhausted"), "plan_gap")  # a named structural cause wins
        # What the live test showed: a tester that ran out of budget looked like a prompt gap and went to the Factory.
        self.assertEqual(fr.route(fr.inferred_category("prompt_gap", "budget_exhausted")), "app")
        self.assertEqual(fr.route(fr.inferred_category("prompt_gap", "round_limit")), "factory")  # for other endings it stays


class Correction(unittest.TestCase):
    def test_a_budget_failure_retries_with_twice_the_money_up_to_the_ceiling(self):
        self.assertEqual(fr.raised_cap("budget_exhausted", 0.08, 10.0), 0.16)
        self.assertEqual(fr.raised_cap("budget_exhausted", 2.0, 10.0), 4.0)
        self.assertEqual(fr.raised_cap("budget_exhausted", 7.0, 10.0), 10.0)
        self.assertIsNone(fr.raised_cap("budget_exhausted", 10.0, 10.0))  # already at the ceiling
        for outcome in ("round_limit", "needs_human", "time_limit", "stuck", "crash"):
            self.assertIsNone(fr.raised_cap(outcome, 0.08), outcome)
        self.assertIsNone(fr.raised_cap("budget_exhausted", None))

    def test_the_app_retry_carries_no_requirements_about_fixing_the_factory(self):
        # What the live retry (#81) got: the post-mortem's requirements about the tester, pasted into the app's request.
        result = dict(RESULT, category="model_limit", requirements=["The tester agent must produce a valid JSON test report", "Helper utilities should make it easier for AI agents"])
        app_side = fr.app_request(FACTS, result, REVERT, "Add a count endpoint.", "model_limit", [])
        self.assertNotIn("tester agent must produce", app_side)
        self.assertNotIn("Helper utilities", app_side)
        factory_side = " ".join(fr.requirements(FACTS, result, REVERT))
        self.assertIn("tester agent must produce", factory_side)  # a Factory fix request keeps them

    def test_a_budget_ending_is_described_as_one_and_not_as_the_agent_that_happened_to_fail(self):
        facts = dict(FACTS, outcome="budget_exhausted", message="$0.0768 spent against a $0.08 cap, and then: the tester produced no file")
        text = fr.app_request(facts, dict(RESULT, root_cause="Tester agent failed to produce valid JSON"), REVERT, "x", "model_limit", [],
                              "The cost cap for this attempt is raised from $0.08 to $0.16, because the last attempt ran out of money.")
        self.assertIn("more than one pass could finish inside its limits", text)
        self.assertNotIn("Tester agent failed to produce valid JSON", text)
        self.assertIn("raised from $0.08 to $0.16", text)


class Retries(unittest.TestCase):
    def test_a_human_intake_is_the_origin_and_its_fix_is_attempt_one(self):
        self.assertEqual(fr.attempt_info("### App name\n\ndemo\n", "66"), ("66", 1, []))

    def test_a_failed_automatic_retry_counts_up_and_remembers_what_earlier_attempts_found(self):
        body = u.with_fix_meta({"origin": 66, "attempt": 1, "history": ["attempt zero: ended round_limit"]}) + "\n\n### App name\n\ndemo\n"
        self.assertEqual(fr.attempt_info(body, "81"), (66, 2, ["attempt zero: ended round_limit"]))

    def test_the_chain_is_bounded_and_only_the_app_route_starts_itself(self):
        lim = {"fix_request_max_attempts": 2}
        self.assertTrue(fr.should_autostart("app", 1, lim))
        self.assertTrue(fr.should_autostart("app", 2, lim))
        self.assertFalse(fr.should_autostart("app", 3, lim))  # a third retry waits for a person
        self.assertFalse(fr.should_autostart("factory", 1, lim))
        self.assertFalse(fr.should_autostart("info", 1, lim))
        self.assertFalse(fr.should_autostart("app", 1, {"fix_request_autostart": False}))
        self.assertTrue(fr.should_autostart("app", 2, {}))  # the default is two retries

    def test_fix_metadata_round_trips_even_with_double_dashes_and_other_issues_have_none(self):
        meta = {"origin": 66, "attempt": 2, "history": ["see https://x/my--run"]}
        self.assertEqual(u.fix_meta(u.with_fix_meta(meta) + "\n\nbody"), meta)
        self.assertEqual(u.with_fix_meta(meta).count("--"), 2)  # only the comment's own delimiters
        for none in ("", None, "no marker", "<!-- factory-fix:{broken -->", "<!-- factory-fix:[1] -->"):
            self.assertEqual(u.fix_meta(none), {})

    def test_the_original_request_is_recovered_so_retries_do_not_nest(self):
        first = fr.app_request(FACTS, RESULT, REVERT, "Retire the flag foo.", "plan_gap", [])
        self.assertEqual(fr.extract_original(first), "Retire the flag foo.")
        second = fr.app_request(FACTS, RESULT, REVERT, first, "plan_gap", ["attempt zero: ended round_limit"])
        self.assertEqual(fr.extract_original(second), "Retire the flag foo.")
        self.assertEqual(second.count("Original request:"), 1)
        self.assertEqual(fr.extract_original("A plain request"), "A plain request")

    def test_a_retry_is_told_how_to_approach_it_and_what_earlier_attempts_found(self):
        text = fr.app_request(FACTS, RESULT, REVERT, "x", "spec_ambiguity", ["attempt zero: ended round_limit: stuck"])
        self.assertIn("Nobody is available to answer questions", text)
        self.assertIn("most conservative reading", text)
        self.assertIn("Earlier attempts:\n- attempt zero: ended round_limit: stuck", text)
        self.assertIn("smallest independently valuable change sets", fr.app_request(FACTS, RESULT, REVERT, "x", "model_limit"))
        self.assertNotIn("How to approach", fr.app_request(FACTS, RESULT, REVERT, "x", "plan_gap"))


class Filing(unittest.TestCase):
    ORIGINAL = "### App name\n\ndemo\n\n### What should change?\n\nRetire the flag foo.\n\n### Cost cap override (USD)\n\n0.75\n"

    def run_it(self, result, existing=None, facts=FACTS, body=None, lim=None):
        calls = []

        def fake(args, token, check=False):
            calls.append(args + [f"TOKEN={token}"])
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps(existing or []))
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout=json.dumps({"body": body if body is not None else self.ORIGINAL}))
            if args[:2] == ["issue", "create"]:
                return mock.Mock(stdout="https://github.com/o/f/issues/80\n")
            return mock.Mock(stdout="")

        with mock.patch.object(fr, "gh", fake), mock.patch.object(u, "gh", fake):
            out = fr.file_fix_request("o/f", "actions-token", "the-pat", facts, result, REVERT, lim if lim is not None else {})
        return out, calls

    def create(self, calls):
        return next(c for c in calls if c[:2] == ["issue", "create"])

    def test_a_factory_cause_files_a_factory_fix_request_and_starts_nothing(self):
        out, calls = self.run_it(RESULT)
        self.assertEqual((out["target"], out["url"], out["started"]), ("factory", "https://github.com/o/f/issues/80", False))
        create = self.create(calls)
        labels = create[create.index("--label") + 1]
        self.assertIn("factory-fix-request", labels)
        self.assertNotIn("update-intake", labels)
        self.assertFalse([c for c in calls if c[:2] == ["issue", "edit"] and u.GO in c])

    def test_an_app_cause_files_an_update_intake_and_starts_it_with_the_pat_so_no_person_is_needed(self):
        out, calls = self.run_it(dict(RESULT, category="spec_ambiguity"))
        self.assertEqual((out["target"], out["started"], out["attempt"]), ("app", True, 1))
        create = self.create(calls)
        labels = create[create.index("--label") + 1]
        for needle in ("update-intake", "app:demo", "auto-fix"):
            self.assertIn(needle, labels)
        self.assertNotIn("needs-human", labels)
        body = create[create.index("--body") + 1]
        self.assertEqual(u.app_name(body), "demo")
        self.assertEqual(u.fix_meta(body)["origin"], "66")
        text = b.parse_intake(body, 2.0, 10.0)
        self.assertEqual(text[1], 0.75)  # the original's cost cap carries over
        self.assertIn("Retire the flag foo.", text[0])
        start = next(c for c in calls if c[:2] == ["issue", "edit"] and u.GO in c)
        self.assertEqual(start[-1], "TOKEN=the-pat")  # events from the Actions token would not start the workflow
        self.assertTrue(any(c[:2] == ["issue", "comment"] and "Superseded by" in c[c.index("--body") + 1] for c in calls))
        self.assertIn("started automatically", body)

    def test_a_budget_failure_files_the_retry_with_a_higher_cap_in_the_form(self):
        facts = dict(FACTS, outcome="budget_exhausted", cap_usd=0.75)
        _, calls = self.run_it(dict(RESULT, category="model_limit"), facts=facts)
        body = self.create(calls)[self.create(calls).index("--body") + 1]
        self.assertEqual(b.parse_intake(body, 2.0, 10.0)[1], 1.5)
        self.assertIn("raised from $0.75 to $1.50", body)

    def test_a_retry_that_fails_files_the_next_attempt_and_closes_the_failed_one(self):
        failed = u.with_fix_meta({"origin": 66, "attempt": 1, "history": ["attempt zero: ended round_limit"]}) + "\n\n" + self.ORIGINAL
        out, calls = self.run_it(dict(RESULT, category="model_limit"), body=failed, facts=dict(FACTS, issue_number="81"))
        self.assertEqual((out["started"], out["attempt"]), (True, 2))
        body = self.create(calls)[self.create(calls).index("--body") + 1]
        meta = u.fix_meta(body)
        self.assertEqual((meta["origin"], meta["attempt"]), (66, 2))
        self.assertEqual(len(meta["history"]), 2)
        self.assertIn("Earlier attempts:", body)
        self.assertTrue(any(c[:3] == ["issue", "close", "81"] for c in calls))

    def test_after_the_last_automatic_retry_it_is_filed_unstarted_and_marked_for_a_person(self):
        failed = u.with_fix_meta({"origin": 66, "attempt": 2, "history": []}) + "\n\n" + self.ORIGINAL
        out, calls = self.run_it(dict(RESULT, category="spec_ambiguity"), body=failed, facts=dict(FACTS, issue_number="82"))
        self.assertEqual((out["started"], out["attempt"]), (False, 3))
        create = self.create(calls)
        self.assertIn("needs-human", create[create.index("--label") + 1])
        self.assertFalse([c for c in calls if c[:2] == ["issue", "edit"] and u.GO in c])  # nothing starts
        self.assertIn("not** started automatically", create[create.index("--body") + 1])

    def test_switching_autostart_off_files_it_unstarted(self):
        out, calls = self.run_it(dict(RESULT, category="spec_ambiguity"), lim={"fix_request_autostart": False})
        self.assertFalse(out["started"])
        self.assertFalse([c for c in calls if c[:2] == ["issue", "edit"] and u.GO in c])

    def test_no_cause_files_an_information_issue_only(self):
        out, calls = self.run_it(None)
        self.assertEqual((out["target"], out["started"]), ("info", False))
        create = self.create(calls)
        self.assertEqual(create[create.index("--label") + 1], "fix-request")

    def test_a_second_failure_of_the_same_attempt_comments_instead_of_filing_again(self):
        fp = fr.fingerprint("demo", "66", "factory", 1)
        existing = [{"number": 80, "title": f"Fix request [{fp}]: plan_gap in demo", "url": "https://github.com/o/f/issues/80"}]
        out, calls = self.run_it(RESULT, existing)
        self.assertEqual(out["url"], "https://github.com/o/f/issues/80")
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertIn("Failed again", comment[comment.index("--body") + 1])


if __name__ == "__main__":
    unittest.main()
