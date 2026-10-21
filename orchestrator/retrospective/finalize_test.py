import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flag_lifecycle import dark_feature  # noqa: E402
from shared import (
    outcomes,  # noqa: E402
    shell,  # noqa: E402
)
from shared import rollback as rollback_step  # noqa: E402
from try_fix import failure_text  # noqa: E402

from retrospective import close_child, lesson_records, run_facts  # noqa: E402
from retrospective import finalize as fin
from retrospective import run_audit as audit


def stages():
    return [{"stage": "Coder", "agent": "coder", "round": "1", "cost_usd": 0.1, "verdict": "pushed", "usage": None}]


class Run:
    d = {"app": "demo", "outcome": "round_limit", "message": "4 rounds without a clean pass", "base_sha": "b" * 40, "head_sha": "h" * 40,
         "commits": ["h" * 40], "release": None}


class Finalize(unittest.TestCase):
    def write_state(self, repo, outcome, extra):
        work = Path(tempfile.mkdtemp())
        state = {**repo.d, "app": "demo", "issue_number": "66", "run_url": "https://x/run/9", "outcome": outcome,
                 "message": "4 review rounds used without a clean pass", "cap_usd": 0.75, "spent_usd": 0.6, "review_passes": 4,
                 "stages": stages(), "blocking": [{"source": "reviewer", "summary": "still wrong"}], "build_kind": "update",
                 **(extra or {})}
        (work / "state.json").write_text(json.dumps(state))
        return work

    def finalize_env(self, work):
        return {"BUILD_RUN_DIR": str(work), "APP_NAME": "demo", "ISSUE_NUMBER": "66", "GITHUB_REPOSITORY": "o/f", "GITHUB_RUN_ID": "9",
                "FACTORY_PAT": "pat", "FACTORY_GH_TOKEN": "tok", "GITHUB_STEP_SUMMARY": str(work / "summary.md")}

    def run_finalize(self, repo, outcome="round_limit", extra=None, rollback=None):
        work = self.write_state(repo, outcome, extra)
        calls = []

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            calls.append(cmd)
            return mock.Mock(stdout="[]", returncode=0, stderr="")

        done = rollback or {"status": "rolled_back", "restored": "b" * 40, "deploy": "healthy"}
        with mock.patch.dict(os.environ, self.finalize_env(work)), mock.patch.object(fin, "sh", fake_sh), mock.patch.object(close_child, "sh", fake_sh), mock.patch.object(shell, "sh", fake_sh), \
                mock.patch.object(rollback_step, "rollback_deploy", return_value=done) as deploy, \
                mock.patch.object(fin.spend_ledger, "record_spend_in_ledger"), mock.patch.object(fin.app_state, "update_state_issues"):
            code = fin.finalize()
        self.deploy = deploy
        report = json.loads((work / "artifacts" / "build-run-report.json").read_text())
        saved = json.loads((work / "state.json").read_text())
        return code, report, saved, (work / "summary.md").read_text(), calls

    def test_a_regression_rolls_the_deploy_back_through_ci_before_anything_is_reported(self):
        code, report, saved, summary, calls = self.run_finalize(Run, "regression")
        self.assertEqual(code, 1)
        self.assertEqual(report["rollback"]["status"], "skipped" if False else "rolled_back")
        self.deploy.assert_called_once()
        self.assertIn("**Rollback**: the live app was redeployed from", summary)
        self.assertEqual(report["audit"], [], msg="a rollback that worked is not an audit finding")
        self.assertEqual(saved["rollback"]["status"], "rolled_back")
        self.assertIn("audit", saved)
        self.assertFalse([c for c in calls if c[0] == "git"], "nothing is committed, pushed or reverted in git")
        failure_issue = next(c for c in calls if c[:3] == ["gh", "issue", "create"])
        self.assertIn("Rollback", Path(failure_issue[failure_issue.index("--body-file") + 1]).read_text(encoding="utf-8"))

    def test_an_update_intake_that_failed_loses_its_go_label_and_says_how_to_retry(self):
        _, _, _, _, calls = self.run_finalize(Run)
        comment = next(c for c in calls if c[:3] == ["gh", "issue", "comment"])
        self.assertIn("add `proceed-with-change` again", comment[comment.index("--body") + 1])
        self.assertTrue(any(c[:3] == ["gh", "issue", "edit"] and "--remove-label" in c for c in calls))

    def test_a_failed_run_that_is_not_a_regression_is_fixed_forward_with_no_rollback(self):
        code, report, saved, summary, calls = self.run_finalize(Run)
        self.assertEqual(code, 1)
        self.assertEqual(report["rollback"]["status"], "skipped")
        self.deploy.assert_not_called()
        self.assertFalse([c for c in calls if c[0] == "git"])
        self.assertEqual(report["audit"], [])

    def test_a_dark_feature_that_failed_its_checks_is_marked_on_its_story(self):
        _, _, _, _, calls = self.run_finalize(Run, extra={"flags": ["thing"]})
        edits = [c for c in calls if c[:3] == ["gh", "issue", "edit"] and "--add-label" in c]
        self.assertTrue(any(c[c.index("--add-label") + 1] == f"{dark_feature.DARK_BROKEN},flag:thing" and c[3] == "66" for c in edits))

    def test_a_provider_block_says_to_top_up_and_does_not_roll_back(self):
        code, report, saved, summary, calls = self.run_finalize(Run, "provider_blocked")
        self.assertEqual(code, 1)
        self.assertEqual(report["rollback"]["status"], "skipped")
        comment = next(c for c in calls if c[:3] == ["gh", "issue", "comment"])
        self.assertIn("topped up", comment[comment.index("--body") + 1])
        self.assertEqual(outcomes.TITLES["provider_blocked"], "Build Run: model provider blocked (account has no balance)")
        self.assertFalse(any(dark_feature.DARK_BROKEN in c for c in calls))

    def test_a_good_ending_and_a_contained_one_are_not_rolled_back(self):
        for outcome, extra in (("released", {"release": {"released": ["demo.feature.x"]}}), ("watchdog_disabled", {})):
            _, report, _, _, _ = self.run_finalize(Run, outcome, extra)
            self.assertEqual(report["rollback"]["status"], "skipped", outcome)
        self.deploy.assert_not_called()

    def test_a_rollback_that_could_not_be_done_is_an_audit_finding_and_a_fix_request_requirement(self):
        failed = {"status": "failed", "restored": "b" * 40, "reason": "could not start rollback-fly.yml"}
        _, report, saved, _, _ = self.run_finalize(Run, "regression", rollback=failed)
        self.assertEqual(report["rollback"]["status"], "failed")
        self.assertTrue(any(a["rule"].startswith("A-07") for a in report["audit"]))
        facts = run_facts.collect_facts(tempfile.mkdtemp(), saved)
        self.assertIn("rollback failed", failure_text.requirements(facts, None, saved["rollback"])[0])
        lessons = lesson_records.lessons_from(facts)
        self.assertEqual(lessons[0]["kind"], "audit_violation", msg="reachable now that state.json carries the audit")


class Policy(unittest.TestCase):
    def test_every_bad_ending_gets_a_fix_request_and_good_ones_do_not(self):
        for outcome in ("round_limit", "needs_human", "stuck", "budget_exhausted", "time_limit", "crash", "watchdog_disabled", "regression"):
            self.assertTrue(lesson_records.wants_fix_request({"outcome": outcome}, {}), outcome)
        for outcome in ("released", "nothing_to_release"):
            self.assertFalse(lesson_records.wants_fix_request({"outcome": outcome}, {}), outcome)
        self.assertFalse(lesson_records.wants_fix_request({"outcome": "crash"}, {"fix_requests": False}))

    def test_the_auditor_wants_a_rollback_only_for_a_regression_and_no_git_revert_ever(self):
        base = {"outcome": "regression", "commits": ["h"], "stages": [], "blocking": []}
        rules = lambda d: [a["rule"][:4] for a in audit.audit_report(d)]
        self.assertEqual(rules(base), ["A-07"])
        self.assertEqual(rules(dict(base, rollback={"status": "rolled_back"})), [])
        self.assertEqual(rules(dict(base, rollback={"status": "failed", "reason": "x"})), ["A-07"])
        self.assertEqual(rules(dict(base, commits=[])), [])
        forward = dict(base, outcome="round_limit")
        self.assertEqual(rules(forward), [], msg="fixed forward: no rollback expected")
        self.assertEqual(rules(dict(forward, revert={"status": "reverted"})), ["A-08"], msg="a git revert in a Report is a broken rule")


if __name__ == "__main__":
    unittest.main()
