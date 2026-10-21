import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import (
    http_client,  # noqa: E402
    rollback,  # noqa: E402
)


def run_state(**over):
    return {"app": "demo", "outcome": "regression", "message": "an old route broke", "base_sha": "b" * 40, "head_sha": "h" * 40,
            "commits": ["h" * 40], "release": None, **over}


class Decision(unittest.TestCase):
    def test_a_regression_that_pushed_something_is_rolled_back(self):
        self.assertEqual(rollback.rollback_decision(run_state()), (True, ""))

    def test_every_other_ending_is_fixed_forward_and_nothing_is_rolled_back(self):
        for outcome in ("round_limit", "needs_human", "stuck", "budget_exhausted", "time_limit", "crash", "running",
                        "released", "nothing_to_release", "planned", "watchdog_disabled", "provider_blocked", "refused"):
            self.assertFalse(rollback.rollback_decision(run_state(outcome=outcome))[0], outcome)

    def test_nothing_pushed_or_nothing_to_return_to_is_a_skip(self):
        for d in (run_state(commits=[]), run_state(base_sha=None)):
            self.assertFalse(rollback.rollback_decision(d)[0])

    def test_switching_it_off_means_off(self):
        self.assertFalse(rollback.rollback_decision(run_state(), enabled=False)[0])


class Sh:

    def __init__(self, lists, dispatch_rc=0):
        self.cmds, self.lists, self.dispatch_rc = [], list(lists), dispatch_rc

    def __call__(self, cmd, cwd=None, env=None, check=True, timeout=None):
        self.cmds.append(cmd)
        if cmd[:3] == ["gh", "run", "list"]:
            return mock.Mock(stdout=json.dumps(self.lists.pop(0) if len(self.lists) > 1 else self.lists[0]), returncode=0)
        if cmd[:3] == ["gh", "workflow", "run"]:
            return mock.Mock(stdout="", stderr="no such workflow", returncode=self.dispatch_rc)
        return mock.Mock(stdout="", stderr="", returncode=0)


class Deploy(unittest.TestCase):
    def go(self, sh, http=None, minutes=5):
        http = (200, {}) if http is None else http
        with mock.patch.object(rollback, "sh", sh), mock.patch.object(http_client, "request", return_value=http), mock.patch.object(rollback.time, "sleep"):
            return rollback.rollback_deploy(run_state(), "demo", "o/demo", "pat", minutes)

    def test_it_dispatches_the_apps_own_workflow_for_the_starting_commit_and_waits_for_health(self):
        sh = Sh([[], [{"databaseId": 7, "status": "completed", "conclusion": "success"}]])
        result = self.go(sh)
        self.assertEqual(result, {"status": "rolled_back", "restored": "b" * 40, "deploy": "healthy"})
        dispatch = next(c for c in sh.cmds if c[:3] == ["gh", "workflow", "run"])
        self.assertEqual((dispatch[3], dispatch[-1]), ("rollback-fly.yml", f"sha={'b' * 40}"))

    def test_a_run_that_was_already_there_is_not_taken_for_this_rollback(self):
        old = {"databaseId": 3, "status": "completed", "conclusion": "success"}
        sh = Sh([[old], [old, {"databaseId": 8, "status": "completed", "conclusion": "failure"}]])
        self.assertEqual(self.go(sh)["deploy"], "deploy_failed")

    def test_nothing_is_ever_committed_pushed_or_reverted_in_git(self):
        sh = Sh([[], [{"databaseId": 7, "status": "completed", "conclusion": "success"}]])
        self.go(sh)
        self.assertEqual([c for c in sh.cmds if c[0] != "gh"], [])

    def test_an_app_without_the_workflow_says_template_sync_adds_it(self):
        result = self.go(Sh([[]], dispatch_rc=1))
        self.assertEqual(result["status"], "failed")
        self.assertIn("template sync", result["reason"])

    def test_an_app_that_does_not_come_back_healthy_is_a_failed_rollback(self):
        sh = Sh([[], [{"databaseId": 7, "status": "completed", "conclusion": "success"}]])
        result = self.go(sh, http=(503, {}))
        self.assertEqual((result["status"], result["deploy"]), ("failed", "unhealthy"))

    def test_a_timeout_and_a_crash_are_reported_and_not_raised(self):
        with mock.patch.object(rollback, "sh", Sh([[]])), mock.patch.object(http_client, "request"), mock.patch.object(rollback.time, "sleep"), \
                mock.patch.object(rollback.time, "time", side_effect=[0, 1, 10 ** 6]):
            self.assertEqual(rollback.rollback_deploy(run_state(), "demo", "o/demo", "pat", 5)["deploy"], "timeout")
        with mock.patch.object(rollback, "sh", side_effect=OSError("gh is gone")):
            self.assertEqual(rollback.rollback_deploy(run_state(), "demo", "o/demo", "pat", 5)["status"], "failed")


class WholeStep(unittest.TestCase):
    def step(self, d, lim=None):
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/f"}), \
                mock.patch.object(rollback, "rollback_deploy", return_value={"status": "rolled_back", "restored": d.get("base_sha"), "deploy": "healthy"}) as dep:
            rollback.rollback_failed_run(d, "pat", lim or {})
        return dep

    def test_a_regression_is_rolled_back_in_the_apps_repo(self):
        d = run_state()
        dep = self.step(d)
        self.assertEqual(d["rollback"]["status"], "rolled_back")
        self.assertEqual(dep.call_args[0][1:3], ("demo", "o/demo"))

    def test_any_other_ending_is_skipped_with_the_reason(self):
        d = run_state(outcome="round_limit")
        dep = self.step(d)
        self.assertEqual(d["rollback"]["status"], "skipped")
        self.assertIn("fixed forward", d["rollback"]["reason"])
        dep.assert_not_called()

    def test_off_is_recorded_and_not_raised(self):
        d = run_state()
        self.step(d, {"rollback_regressions": False})
        self.assertEqual(d["rollback"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
