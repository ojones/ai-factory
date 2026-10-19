# A model provider that refuses every request because the account has no balance (found when DeepInfra answered 402 mid-session).
# Nothing retries, files a self-starting fix request or runs a retrospective Agent for it; one alert asks for a top-up.
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_run as b  # noqa: E402
import fixrequest as fr  # noqa: E402
import retrospective as pm  # noqa: E402
from shared import github, http_client, outcomes, provider, run_stops, spend_budget  # noqa: E402

# The event OpenHands printed, taken from the real log.
REAL_EVENT = ('{"id": "af67", "timestamp": "2026-10-12T14:10:40", "source": "environment", "code": "LLMBadRequestError", '
              '"detail": "litellm.BadRequestError: OpenAIException - You need positive balance to do inference. '
              'Please add balance manually or setup top-up", "kind": "ConversationErrorEvent"}')


def tmpfile(text):
    f = Path(tempfile.mkdtemp()) / "agent.jsonl"
    f.write_text(text)
    return f


class Detection(unittest.TestCase):
    def test_the_real_error_event_is_recognised(self):
        self.assertTrue(provider.provider_blocked_text("some output\n" + REAL_EVENT + "\nGoodbye"))

    def test_a_prompt_or_a_log_that_only_mentions_balances_is_not(self):
        self.assertFalse(provider.provider_blocked_text("The spec says: check the account has a positive balance before charging."))
        self.assertFalse(provider.provider_blocked_text('{"kind": "ConversationErrorEvent", "detail": "context length exceeded"}'))
        self.assertFalse(provider.provider_blocked_text("insufficient funds in the checkout test"))  # no error event on the line
        self.assertFalse(provider.provider_blocked_text(""))
        self.assertFalse(provider.provider_blocked_text(None))

    def test_scanning_an_agent_file_looks_only_at_its_end_and_survives_a_missing_file(self):
        self.assertEqual(provider.scan_for_provider_block(tmpfile("a\n" * 100 + REAL_EVENT + "\n")), provider.BLOCKED_MESSAGE)
        self.assertIsNone(provider.scan_for_provider_block(tmpfile('{"kind": "ActionEvent"}\n')))
        self.assertIsNone(provider.scan_for_provider_block("/nonexistent/agent.jsonl"))
        early = REAL_EVENT + "\n" + ("x" * 100 + "\n") * 5000  # an old error followed by plenty of normal output
        self.assertIsNone(provider.scan_for_provider_block(tmpfile(early), tail_bytes=20_000))

    def test_the_message_says_what_to_do(self):
        for needle in ("no balance", "402", "add `proceed-with-change` again"):
            self.assertIn(needle, provider.BLOCKED_MESSAGE)


class Places(unittest.TestCase):
    def test_the_preflight_stops_a_run_before_it_does_any_work(self):
        with mock.patch.object(http_client, "request", return_value=(402, {"error": {"message": "You need positive balance"}})):
            with self.assertRaises(run_stops.ProviderBlocked):
                provider.provider_check("https://x/v1", "key", "m")
        with mock.patch.object(http_client, "request", return_value=(400, "BadRequestError ... You need positive balance to do inference")):
            with self.assertRaises(run_stops.ProviderBlocked):
                provider.provider_check("https://x/v1", "key", "m")

    def test_other_answers_are_not_this_condition(self):
        for answer in ((200, {"choices": []}), (500, "boom"), (0, "timed out"), (429, "slow down"), (403, "token spending limit exceeded"),
                       (400, "BadRequestError: context length")):
            with mock.patch.object(http_client, "request", return_value=answer):
                provider.provider_check("https://x/v1", "key", "m")  # does not raise

    def test_a_402_when_minting_a_credential_is_a_provider_block_and_other_failures_are_not(self):
        with mock.patch.object(http_client, "request", return_value=(402, {})):
            with self.assertRaises(run_stops.ProviderBlocked):
                spend_budget.Budget("admin", 2.0, 100).mint("m")
        with mock.patch.object(http_client, "request", return_value=(500, {})):
            with self.assertRaises(RuntimeError):
                spend_budget.Budget("admin", 2.0, 100).mint("m")

    def test_the_single_call_reviewer_does_not_fall_back_to_the_agent_on_a_402(self):
        with mock.patch.object(http_client, "request", return_value=(402, {})):
            with self.assertRaises(run_stops.ProviderBlocked):
                b.single_call_review("https://x/v1", "k", "m", "sys", "user")
        with mock.patch.object(http_client, "request", return_value=(500, {})), mock.patch.object(b.time, "sleep"):
            with self.assertRaises(b.FastReviewFailed):
                b.single_call_review("https://x/v1", "k", "m", "sys", "user", attempts=2)


class Run(unittest.TestCase):
    def test_a_blocked_provider_ends_the_run_as_provider_blocked_and_nothing_else(self):
        run = object.__new__(b.BuildRun)
        run.state = b.State("/tmp/unused-state.json", "demo", "1", "u")
        run.state.save = lambda: None
        run.setup = mock.Mock(side_effect=run_stops.ProviderBlocked(provider.BLOCKED_MESSAGE))
        run.run()
        self.assertEqual(run.state.d["outcome"], "provider_blocked")
        self.assertIn("no balance", run.state.d["message"])

    def test_it_is_not_a_good_ending_and_is_not_rolled_back_either(self):
        self.assertNotIn("provider_blocked", outcomes.OK)
        d = {"outcome": "provider_blocked", "commits": ["h"], "base_sha": "b", "head_sha": "h", "release": None}
        self.assertFalse(b.rollback_decision(d)[0])  # code is fixed forward; only a regression rolls the deploy back


class AfterwardsOnlyOneAlert(unittest.TestCase):
    FACTS = {"app": "demo", "run_url": "https://x/run/9", "issue_number": "66", "rollback": {"status": "rolled_back", "restored": "01234567", "deploy": "healthy"}}

    def test_no_self_starting_retry_no_lesson_no_stuck_issue(self):
        self.assertFalse(pm.wants_fix_request({"outcome": "provider_blocked"}, {}))
        self.assertFalse(pm.records_stuck_issue("provider_blocked"))
        self.assertTrue(pm.wants_fix_request({"outcome": "round_limit"}, {}))
        self.assertTrue(pm.records_stuck_issue("round_limit"))

    def fake(self, existing):
        calls = []

        def run(args, token):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps(existing))
            if args[:2] == ["issue", "create"]:
                return mock.Mock(stdout="https://github.com/o/f/issues/90\n")
            return mock.Mock(stdout="")

        return run, calls

    def test_the_first_blocked_run_files_one_alert_that_says_what_to_do(self):
        run, calls = self.fake([])
        with mock.patch.object(github, "run", lambda a, t, check=False: run(a, t)):
            url = fr.file_provider_alert("o/f", "tok", self.FACTS)
        self.assertEqual(url, "https://github.com/o/f/issues/90")
        create = next(c for c in calls if c[:2] == ["issue", "create"])
        self.assertIn("provider-blocked", create[create.index("--label") + 1])
        body = create[create.index("--body") + 1]
        for needle in ("no balance", "Add balance", "proceed-with-change", "ready-for-staging", "redeployed", "no fix request or retrospective"):
            self.assertIn(needle, body)

    def test_later_blocked_runs_comment_on_the_open_alert_instead_of_filing_more(self):
        run, calls = self.fake([{"number": 90, "url": "https://github.com/o/f/issues/90"}])
        with mock.patch.object(github, "run", lambda a, t, check=False: run(a, t)):
            url = fr.file_provider_alert("o/f", "tok", dict(self.FACTS, app="other"))
        self.assertEqual(url, "https://github.com/o/f/issues/90")
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])
        self.assertTrue(any(c[:2] == ["issue", "comment"] and "Blocked again" in c[c.index("--body") + 1] for c in calls))


if __name__ == "__main__":
    unittest.main()
