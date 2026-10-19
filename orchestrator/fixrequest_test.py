import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_run as b  # noqa: E402
import fixrequest as fr  # noqa: E402
import update_intake as u  # noqa: E402
from request import intake_labels, read_form, render_form  # noqa: E402
from shared import github  # noqa: E402

FACTS = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass", "run_url": "https://x/run/9",
         "issue_number": "66", "review_passes": 4, "spent_usd": 0.61, "cap_usd": 0.75, "commits": ["a", "b"],
         "final_blocking": ["the change is not behind the flag the spec names", "put still 404s while that flag is off"],
         "recurring_findings": ["flag the spec names"]}
REVERT = {"status": "rolled_back", "restored": "0123456789ab", "deploy": "healthy"}
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

    def test_a_failed_rollback_is_the_first_requirement_and_said_plainly(self):
        failed = {"status": "failed", "reason": "could not start rollback-fly.yml"}
        self.assertIn("rollback failed", fr.requirements(FACTS, RESULT, failed)[0])
        self.assertIn("**The automatic rollback failed**", fr.rollback_line(failed))
        self.assertIn("run `rollback-fly.yml`", fr.rollback_line(failed))
        regression = dict(FACTS, outcome="regression")
        self.assertIn("no rollback was done", fr.requirements(regression, RESULT, {"status": "skipped", "reason": "switched off"})[0])
        self.assertEqual(fr.rollback_line(None), "No rollback was attempted.")
        self.assertIn("Nothing was reverted in git", fr.rollback_line(REVERT))

    def test_a_regression_is_fixed_forward_on_its_own_story_behind_the_same_flag(self):
        self.assertEqual(fr.route(fr.inferred_category(None, "regression")), "app")
        self.assertEqual(fr.route(fr.inferred_category("prompt_gap", "regression")), "factory")
        text = " ".join(fr.requirements(dict(FACTS, outcome="regression", message="old route broke"), None, REVERT))
        self.assertIn("fix it forward", text)
        self.assertNotIn("deliver it again", text)

    def test_bugs_the_tester_saw_are_requirements_and_send_the_story_back_to_its_own_issue(self):
        bugs = [{"kind": "dark", "flag": "pin", "check": "pin route answers 201", "evidence": "got 500", "repro": "curl -X POST /api/pins"}]
        facts = dict(FACTS, bugs=bugs)
        text = " ".join(fr.requirements(facts, None, None))
        self.assertIn("Fix this bug the tester saw (the new change, still dark): pin route answers 201", text)
        self.assertIn("Repro: curl -X POST /api/pins", text)
        # a dark failure with no cause named, or an infra one, is retried on the story (not an information issue in the Factory)
        for category in (None, "infra", "unknown", "model_limit"):
            self.assertEqual(fr.route(fr.inferred_category(category, "round_limit", True)), "app", category)
        self.assertEqual(fr.route(fr.inferred_category(None, "round_limit", False)), "info")
        # a Factory cause still goes to the Factory
        self.assertEqual(fr.route(fr.inferred_category("prompt_gap", "round_limit", True)), "factory")
        self.assertIn("listed under the requirements", fr.GUIDANCE["regression"])

    def test_the_issue_explains_what_happened_what_was_done_and_what_to_do_next(self):
        body = fr.render(FACTS, RESULT, REVERT, "factory", "https://github.com/o/f/issues/66")
        for needle in ("## What happened", "ended **round_limit**", "https://x/run/9", "Still blocking at the end: the change is not behind",
                       "## What was done automatically", "the deploy is **healthy**", "## Analysis (automated, and may be wrong)",
                       "**plan_gap**", "invented a flag", "## Requirements", "1. ", "ready-for-factory-run"):
            self.assertIn(needle, body, needle)
        self.assertIn("proceed-with-change", fr.render(FACTS, RESULT, REVERT, "app"))
        self.assertIn("did not name a cause", fr.render(FACTS, None, REVERT, "info"))

    def test_the_app_request_carries_the_original_and_the_requirements_and_parses_as_a_form(self):
        text = fr.app_request(FACTS, RESULT, REVERT, "Retire the flag foo.")
        for needle in ("did not complete", "round_limit", "Retire the flag foo.", "Requirements for this attempt:"):
            self.assertIn(needle, text)
        self.assertNotIn("invented a flag", text)  # a Factory-side cause is not the app request's business
        issue = fr.render(FACTS, RESULT, REVERT, "app") + "\n---\n\n" + render_form.form_body("demo", text)
        self.assertEqual(read_form.app_name(issue), "demo")
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
    def test_a_retry_never_gets_more_money_than_the_request_had(self):
        self.assertFalse(hasattr(fr, "raised_cap"))

    def test_the_app_retry_carries_no_requirements_about_fixing_the_factory(self):
        # What the live retry (#81) got: the retrospective's requirements about the tester, pasted into the app's request.
        result = dict(RESULT, category="model_limit", requirements=["The tester agent must produce a valid JSON test report", "Helper utilities should make it easier for AI agents"])
        app_side = fr.app_request(FACTS, result, REVERT, "Add a count endpoint.", "model_limit", [])
        self.assertNotIn("tester agent must produce", app_side)
        self.assertNotIn("Helper utilities", app_side)
        factory_side = " ".join(fr.requirements(FACTS, result, REVERT))
        self.assertIn("tester agent must produce", factory_side)  # a Factory fix request keeps them

    def test_a_budget_ending_is_described_as_one_and_not_as_the_agent_that_happened_to_fail(self):
        facts = dict(FACTS, outcome="budget_exhausted", message="$0.0768 spent against a $0.08 cap, and then: the tester produced no file")
        text = fr.app_request(facts, dict(RESULT, root_cause="Tester agent failed to produce valid JSON"), REVERT, "x", "model_limit", [],
                              "The last attempt ran out of money, and the cost cap is not raised for this one: do less in one pass.")
        self.assertIn("more than one pass could finish inside its limits", text)
        self.assertNotIn("Tester agent failed to produce valid JSON", text)
        self.assertIn("not raised for this one", text)


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

    def run_it(self, result, existing=None, facts=FACTS, body=None, lim=None, comments=()):
        calls = []

        def fake(args, token, check=False):
            calls.append(args + [f"TOKEN={token}"])
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps(existing or []))
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout=json.dumps({"body": body if body is not None else self.ORIGINAL, "url": "https://github.com/o/f/issues/66",
                                                    "comments": [{"body": c} for c in comments]}))
            if args[:2] == ["issue", "create"]:
                return mock.Mock(stdout="https://github.com/o/f/issues/80\n")
            return mock.Mock(stdout="")

        with mock.patch.object(github, "run", fake):
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
        self.assertNotIn("update-app-intake", labels)
        self.assertFalse([c for c in calls if c[:2] == ["issue", "edit"] and intake_labels.START in c])

    def state_of(self, calls):
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        return comment[comment.index("--body") + 1], fr.retry_state([comment[comment.index("--body") + 1]])

    def started(self, calls):
        return [c for c in calls if c[:2] == ["issue", "edit"] and intake_labels.START in c]

    def test_an_app_cause_updates_the_same_issue_and_restarts_it_with_the_pat_so_no_person_is_needed(self):
        out, calls = self.run_it(dict(RESULT, category="spec_ambiguity"))
        self.assertEqual((out["target"], out["started"], out["attempt"], out["url"]), ("app", True, 1, "https://github.com/o/f/issues/66"))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])  # no new issue: the story keeps its own
        text, state = self.state_of(calls)
        self.assertIn("## Attempt zero did not complete", text)
        self.assertIn("retried automatically", text)
        self.assertEqual((state["attempt"], state["last_run"]), (1, "https://x/run/9"))
        self.assertIn("Nobody is available to answer questions", state["guidance"])
        self.assertEqual(self.started(calls)[0][-1], "TOKEN=the-pat")  # events from the Actions token would not start the workflow
        self.assertTrue(any(c[:3] == ["issue", "edit", "66"] and "retrying" in c for c in calls))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "close"]])

    def test_a_budget_failure_retries_the_same_issue_with_the_same_cap_and_a_note_to_do_less(self):
        _, calls = self.run_it(dict(RESULT, category="model_limit"), facts=dict(FACTS, outcome="budget_exhausted", cap_usd=0.75))
        _, state = self.state_of(calls)
        self.assertNotIn("cap", state)
        self.assertIn("cost cap is not raised for this one", state["guidance"])
        self.assertNotIn("raised from", state["guidance"])

    def test_a_watchdog_switch_off_retries_the_story_with_the_same_flag(self):
        out, calls = self.run_it(None, facts=dict(FACTS, outcome="watchdog_disabled", message="errors rose", flags=["todo-ui"]))
        self.assertEqual((out["target"], out["started"]), ("app", True))
        text, state = self.state_of(calls)
        self.assertEqual(state["flags"], ["todo-ui"])
        self.assertIn("use exactly `todo-ui`", state["guidance"])
        self.assertIn("fix the code behind the same flag", state["guidance"])
        self.assertIn("Feature flag of this story: `todo-ui`", text)

    def test_a_retry_that_fails_updates_the_same_issue_again_and_remembers_the_flag_and_what_was_found(self):
        earlier = "text\n" + fr.with_retry_state({"attempt": 1, "flags": ["todo-ui"], "history": ["attempt zero: ended round_limit: x"], "last_run": "https://x/run/1", "cap": None})
        out, calls = self.run_it(dict(RESULT, category="model_limit"), comments=[earlier])
        self.assertEqual((out["started"], out["attempt"]), (True, 2))
        _, state = self.state_of(calls)
        self.assertEqual((state["attempt"], state["flags"]), (2, ["todo-ui"]))  # the flag survives a failure that did not name one
        self.assertEqual(len(state["history"]), 2)
        self.assertIn("Earlier attempts:", state["guidance"])
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])

    def test_after_the_last_automatic_retry_the_issue_stays_open_for_a_person_attached_to_its_flag(self):
        earlier = fr.with_retry_state({"attempt": 2, "flags": ["todo-ui"], "history": [], "last_run": "https://x/run/1"})
        out, calls = self.run_it(dict(RESULT, category="spec_ambiguity"), comments=[earlier])
        self.assertEqual((out["started"], out["attempt"]), (False, 3))
        self.assertFalse(self.started(calls))  # nothing starts
        self.assertTrue(any(c[:3] == ["issue", "edit", "66"] and "needs-human" in c and "--add-label" in c for c in calls))
        text, state = self.state_of(calls)
        self.assertIn("not** retried automatically", text)
        self.assertIn("todo-ui", text)
        self.assertEqual(state["flags"], ["todo-ui"])

    def test_the_same_failure_reported_twice_does_not_add_a_second_attempt(self):
        earlier = fr.with_retry_state({"attempt": 1, "flags": [], "history": [], "last_run": FACTS["run_url"]})
        out, calls = self.run_it(dict(RESULT, category="spec_ambiguity"), comments=[earlier])
        self.assertEqual(out["attempt"], 1)
        self.assertFalse([c for c in calls if c[:2] == ["issue", "comment"]])
        self.assertFalse(self.started(calls))

    def test_switching_autostart_off_leaves_the_issue_for_a_person(self):
        out, calls = self.run_it(dict(RESULT, category="spec_ambiguity"), lim={"fix_request_autostart": False})
        self.assertFalse(out["started"])
        self.assertFalse(self.started(calls))

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

class FlagMissingRequirements(unittest.TestCase):
    def test_a_missing_flag_asks_for_the_flag_the_task_names_and_says_nothing_was_rolled_back(self):
        facts = {"outcome": "flag_missing", "message": "Not released: `x` ...", "flag_notes": [{"slug": "x", "kind": "missing_dark", "guess": "g"}], "commits": ["h"]}
        reqs = fr.requirements(facts, None, None)
        self.assertTrue(any("exists in GrowthBook" in r and "`x`" in r and "Nothing was rolled back" in r for r in reqs))



if __name__ == "__main__":
    unittest.main()
