import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shared import agent_process, agent_runner, provider
from shared.run_stops import BudgetExhausted, NeedsHuman, ProviderBlocked

CFG = {"roles": {"coder": {"model": "fast"}, "tester": {"model": "t"}}, "provider": {"base_url": "https://llm"},
       "limits": {"agent_timeout_minutes": 5, "agent_stall_minutes": 2, "context_goal_tokens": 1000}}


class FakeBudget:
    cap = 2.0

    def __init__(self, spent=0.25):
        self.tokens, self.minted, self.spent = {}, [], spent

    def mint(self, model):
        self.minted.append(model)
        self.tokens["jwt-1"] = self.spent
        return "jwt-1"


def runner_in(tmp, cfg=CFG, budget=None, **kw):
    return agent_runner.AgentRunner(cfg, budget or FakeBudget(), Path(tmp) / "art", Path(tmp) / "work", Path(tmp) / "app", **kw)


def with_dirs(tmp):
    (Path(tmp) / "art").mkdir()
    (Path(tmp) / "work").mkdir()
    return tmp


class Models(unittest.TestCase):
    def runner(self, coder):
        return agent_runner.AgentRunner({"roles": {"coder": coder, "tester": {"model": "t"}}}, None, "a", "w", "c")

    def test_every_attempt_uses_model_unless_fix_model_is_set(self):
        self.assertEqual([self.runner({"model": "fast"}).model_for("coder", l) for l in ("1", "2", "fix1")], ["fast"] * 3)

    def test_fix_model_takes_over_after_round_one_for_the_coder_only(self):
        runner = self.runner({"model": "fast", "fix_model": "big"})
        self.assertEqual([runner.model_for("coder", l) for l in ("1", "2", "fix1")], ["fast", "big", "big"])
        self.assertEqual(runner.model_for("tester", "t2"), "t")


class Environment(unittest.TestCase):
    def test_the_agent_gets_its_credential_model_and_provider_and_a_home_when_given_one(self):
        env = runner_in("x").agent_env("coder", "the-jwt", extra={"A": "1"}, home="/h")
        self.assertEqual((env["LLM_API_KEY"], env["LLM_MODEL"], env["LLM_BASE_URL"], env["HOME"], env["A"]), ("the-jwt", "openai/fast", "https://llm", "/h", "1"))


class Run(unittest.TestCase):
    def run_agent(self, tmp, rc=0, jsonl_text="", spent_cap_hit=False, **kw):
        with_dirs(tmp)
        spends = []
        runner = runner_in(tmp, on_spend=lambda jwt: spends.append(jwt) or 0.25, **kw)

        def fake_watched(cmd, cwd, env, out, timeout_s, stall_s, user=None, pidfile=None, **k):
            Path(out).write_text(jsonl_text, encoding="utf-8")
            self.watched = {"cmd": cmd, "cwd": cwd, "env": env, "timeout": timeout_s, "stall": stall_s, "user": user, "pidfile": pidfile}
            return rc

        with mock.patch.object(agent_process, "run_watched", fake_watched), mock.patch("builtins.print"):
            result = runner.run("coder", "1", "do it", home=Path(tmp) / "home")
        return runner, result, spends

    def test_it_mints_a_credential_for_the_roles_model_runs_the_agent_and_returns_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, (rc, cost, usage), spends = self.run_agent(tmp)
        self.assertEqual((rc, cost, usage), (0, 0.25, None))
        self.assertEqual(runner.budget.minted, ["fast"])
        self.assertEqual(spends, ["jwt-1"])
        self.assertEqual(self.watched["cmd"][-1], "do it")
        self.assertEqual((self.watched["timeout"], self.watched["stall"]), (300, 120.0))
        self.assertEqual(self.watched["env"]["LLM_API_KEY"], "jwt-1")

    def test_the_limits_are_checked_before_anything_is_minted(self):
        def stop():
            raise BudgetExhausted("spent")
        with tempfile.TemporaryDirectory() as tmp:
            with_dirs(tmp)
            runner = runner_in(tmp, check_limits=stop)
            with self.assertRaises(BudgetExhausted):
                runner.run("coder", "1", "p")
            self.assertEqual(runner.budget.minted, [])

    def test_an_agent_run_as_another_user_gets_a_home_of_its_own_and_a_pid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with_dirs(tmp)
            runner = runner_in(tmp, agent_user="agent")
            with mock.patch.object(agent_process, "run_watched", return_value=0) as watched, mock.patch("builtins.print"), \
                    mock.patch.dict("os.environ", {"RUNNER_TEMP": str(Path(tmp) / "temp")}), mock.patch("shared.agent_runner.subprocess.run"):
                runner.run("coder", "1", "p")
            self.assertEqual(len(list((Path(tmp) / "temp" / "sealed-agent-homes").glob("home-agent-*"))), 1)
            self.assertEqual(watched.call_args[1]["user"], "agent")
            self.assertTrue(str(watched.call_args[1]["pidfile"]).endswith("pgid-coder-1.txt"))

    def test_a_provider_with_no_balance_stops_the_run_even_though_the_agent_exited(self):
        text = json.dumps({"kind": "ConversationErrorEvent", "detail": "BadRequestError: You need positive balance to do inference"})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProviderBlocked):
                self.run_agent(tmp, rc=1, jsonl_text=text)

    def test_the_conversation_the_agent_created_is_summarised_and_kept(self):
        state = {"stats": {"usage_to_metrics": {"agent": {"token_usages": [{"prompt_tokens": 500, "completion_tokens": 5}], "response_latencies": []}}}}
        with tempfile.TemporaryDirectory() as tmp:
            with_dirs(tmp)
            runner = runner_in(tmp, on_spend=lambda jwt: 0.25)

            def fake_watched(cmd, cwd, env, out, *a, **k):
                conv = Path(tmp) / "home" / ".openhands" / "conversations" / "c1"
                conv.mkdir(parents=True)
                (conv / "base_state.json").write_text(json.dumps(state))
                Path(out).write_text("", encoding="utf-8")
                return 0

            with mock.patch.object(agent_process, "run_watched", fake_watched), mock.patch("builtins.print"):
                _, _, usage = runner.run("coder", "1", "p", home=Path(tmp) / "home")
            self.assertEqual((usage["calls"], usage["peak_context"]), (1, 500))
            self.assertTrue((Path(tmp) / "art" / "openhands-coder-1-state.json").exists())


class JsonOutput(unittest.TestCase):
    def attempts(self, path, writes):
        calls = []

        def attempt(label, note):
            calls.append((label, note))
            what = writes[len(calls) - 1]
            if what is not None:
                Path(path).write_text(what, encoding="utf-8")
            return 0, 0.1, None
        return attempt, calls

    def go(self, path, writes, **kw):
        attempt, calls = self.attempts(path, writes)
        failed = []
        out = agent_runner.json_output(attempt, path, "tester", "t1", lambda r, l: Path(path).with_name("none.jsonl"), record_failed=lambda *a: failed.append(a), **kw)
        return out, calls, failed

    def test_a_good_file_on_the_first_attempt_is_returned_with_its_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            (doc, cost, _), calls, failed = self.go(f"{tmp}/o.json", ['{"a": 1}'])
        self.assertEqual((doc, round(cost, 2), [c[0] for c in calls], failed), ({"a": 1}, 0.1, ["t1"], []))

    def test_a_missing_file_gets_one_retry_that_is_told_what_was_wrong(self):
        with tempfile.TemporaryDirectory() as tmp:
            (doc, cost, _), calls, _ = self.go(f"{tmp}/o.json", [None, '{"a": 2}'])
        self.assertEqual((doc, round(cost, 2), [c[0] for c in calls]), ({"a": 2}, 0.2, ["t1", "t1b"]))
        self.assertIn("was not written", calls[1][1])

    def test_two_bad_attempts_stop_the_run_for_a_person_and_the_cost_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt, _ = self.attempts(f"{tmp}/o.json", ["not json", "{"])
            failed = []
            with self.assertRaisesRegex(NeedsHuman, "no valid output file twice"):
                agent_runner.json_output(attempt, f"{tmp}/o.json", "tester", "t1", lambda r, l: Path(tmp) / "none", record_failed=lambda *a: failed.append(a))
        self.assertEqual((round(failed[0][0], 2), failed[0][1]), (0.2, "no usable output after 2 attempt(s)"))

    def test_an_agent_that_spent_its_whole_credential_is_not_given_a_second_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "t.jsonl"
            log.write_text("token spending limit exceeded")
            attempt, calls = self.attempts(f"{tmp}/o.json", [None, '{"a": 1}'])
            with self.assertRaisesRegex(NeedsHuman, "spent its whole credential"):
                agent_runner.json_output(attempt, f"{tmp}/o.json", "tester", "t1", lambda r, l: log)
        self.assertEqual(len(calls), 1)

    def test_a_rejecting_check_counts_as_a_bad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (doc, _, _), calls, _ = self.go(f"{tmp}/o.json", ['{"ok": false}', '{"ok": true}'], check=lambda d: d["ok"])
        self.assertEqual(doc, {"ok": True})
        self.assertIn("not accepted", calls[1][1])


class Provider(unittest.TestCase):
    def test_the_runner_uses_the_providers_own_wording_to_spot_an_empty_account(self):
        self.assertTrue(provider.provider_blocked_text("BadRequestError: You need positive balance"))


class SealHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="seal-test-")
        self.home = Path(self.tmp) / "work" / "home-tester-1"
        (self.home / ".openhands").mkdir(parents=True)
        (self.home / ".openhands" / "events.json").write_text("{}", encoding="utf-8")
        self.sealed = Path(self.tmp) / "temp"

    def seal(self, agent_user):
        with mock.patch.dict("os.environ", {"RUNNER_TEMP": str(self.sealed)}), mock.patch("shared.agent_runner.subprocess.run") as run:
            runner_in(self.tmp, agent_user=agent_user).seal_home(self.home)
        return run

    def test_a_finished_agents_home_leaves_the_agents_reach_with_its_files(self):
        self.seal("agent")
        self.assertFalse(self.home.exists())
        moved = list((self.sealed / "sealed-agent-homes").glob("home-tester-1-*"))
        self.assertEqual(len(moved), 1)
        self.assertTrue((moved[0] / ".openhands" / "events.json").exists())

    def test_the_orchestrator_takes_the_agents_files_before_moving_them(self):
        run = self.seal("agent")
        self.assertEqual(run.call_args.args[0][:5], ["sudo", "-n", "chown", "-R", f"{os.getuid()}:{os.getgid()}"])

    def test_a_finished_agents_logs_become_private_to_the_orchestrator(self):
        art = Path(self.tmp) / "art"
        art.mkdir()
        log_file, other = art / "openhands-tester-t1.jsonl", art / "progress.json"
        for f in (log_file, other):
            f.write_text("{}", encoding="utf-8")
            f.chmod(0o644)
        runner_in(self.tmp, agent_user="agent").seal_logs("tester", "t1")
        self.assertEqual(log_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(other.stat().st_mode & 0o777, 0o644)

    def test_a_secret_the_agent_printed_is_removed_from_its_logs(self):
        art = Path(self.tmp) / "art"
        art.mkdir()
        log_file = art / "openhands-tester-t1.jsonl"
        log_file.write_text('{"output": "s3cr3t-token\\n"}', encoding="utf-8")
        runner_in(self.tmp, agent_user=None).seal_logs("tester", "t1", ["s3cr3t-token", ""])
        self.assertEqual(log_file.read_text(encoding="utf-8"), '{"output": "[redacted]\\n"}')

    def test_a_secret_the_log_escaped_is_removed_too(self):
        art = Path(self.tmp) / "art"
        art.mkdir()
        log_file = art / "openhands-tester-t1.jsonl"
        log_file.write_text('{"output": "ab\\"cd\\\\ef"}', encoding="utf-8")
        runner_in(self.tmp, agent_user=None).seal_logs("tester", "t1", ['ab"cd\\ef'])
        self.assertEqual(log_file.read_text(encoding="utf-8"), '{"output": "[redacted]"}')

    def test_a_secret_in_an_uploaded_report_is_removed(self):
        work = Path(self.tmp) / "work"
        report = work / "test-report-1.json"
        report.write_text('{"note": "s3cr3t-token"}', encoding="utf-8")
        runner_in(self.tmp, agent_user=None).redact_uploads(["s3cr3t-token"])
        self.assertEqual(report.read_text(encoding="utf-8"), '{"note": "[redacted]"}')

    def test_a_report_that_cannot_be_rewritten_does_not_stop_the_run(self):
        work = Path(self.tmp) / "work"
        (work / "test-report-1.json").write_text('{"note": "s3cr3t-token"}', encoding="utf-8")
        with mock.patch("shared.agent_runner.redact", side_effect=PermissionError):
            runner_in(self.tmp, agent_user=None).redact_uploads(["s3cr3t-token"])

    def test_a_failed_seal_says_why(self):
        error = subprocess.CalledProcessError(1, "sudo", stderr=b"sudo: a password is required\n")
        with mock.patch("shared.agent_runner.AgentRunner.take_ownership", side_effect=error), mock.patch("shared.agent_runner.log") as say:
            self.seal("agent")
        self.assertIn("a password is required", say.call_args.args[0])

    def test_a_value_too_short_to_be_a_secret_is_left_alone(self):
        self.assertEqual(agent_runner.redacted("a p b", ["p"]), "a p b")

    def test_a_lowercase_credential_name_is_a_secret(self):
        self.assertEqual(agent_runner.secret_values("jwt", {"api_key": "k"}), ["jwt", "k"])

    def test_a_chown_that_times_out_leaves_the_home_and_the_run_goes_on(self):
        with mock.patch("shared.agent_runner.AgentRunner.take_ownership", side_effect=subprocess.TimeoutExpired("sudo", 60)):
            self.seal("agent")
        self.assertTrue(self.home.exists())

    def test_only_credentials_among_the_extra_environment_are_secrets(self):
        env = {"PREVIEW_TOKEN": "p", "API_CHECK_BASE": "https://app", "UI_CHECK_DIR": "/w"}
        self.assertEqual(agent_runner.secret_values("jwt", env), ["jwt", "p"])

    def test_without_isolation_the_home_stays_where_it_is(self):
        self.seal(None)
        self.assertTrue(self.home.exists())

    def test_without_a_runner_temp_the_home_stays_where_it_is(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            runner_in(self.tmp, agent_user="agent").seal_home(self.home)
        self.assertTrue(self.home.exists())

    def test_a_home_that_cannot_be_moved_is_left_and_the_run_goes_on(self):
        with mock.patch("shared.agent_runner.shutil.move", side_effect=PermissionError):
            self.seal("agent")
        self.assertTrue(self.home.exists())


if __name__ == "__main__":
    unittest.main()
