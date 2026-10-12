"""The finalize step end to end for a failed run: a real git repo, gh mocked."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit  # noqa: E402
import build_run as b  # noqa: E402
import fixrequest  # noqa: E402
import postmortem as pm  # noqa: E402
from test_revert import Repo, git  # noqa: E402


def stages():
    return [{"stage": "Coder", "agent": "coder", "round": "1", "cost_usd": 0.1, "verdict": "pushed", "usage": None}]


class Finalize(unittest.TestCase):
    def run_finalize(self, repo, outcome="round_limit", extra=None):
        work = Path(tempfile.mkdtemp())
        state = {**repo.d, "app": "demo", "issue_number": "66", "run_url": "https://x/run/9", "outcome": outcome,
                 "message": "4 review rounds used without a clean pass", "cap_usd": 0.75, "spent_usd": 0.6, "review_passes": 4,
                 "stages": stages(), "blocking": [{"source": "reviewer", "summary": "still wrong"}], "build_kind": "update",
                 "intake_kind": "update", **(extra or {})}
        (work / "state.json").write_text(json.dumps(state))
        gh_calls = []

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            if cmd[0] == "gh":
                gh_calls.append(cmd)
                return mock.Mock(stdout="[]", returncode=0, stderr="")
            return real_sh(cmd, cwd=cwd, env=env, check=check, timeout=timeout)

        real_sh = b.sh
        env = {"BUILD_RUN_DIR": str(work), "APP_NAME": "demo", "ISSUE_NUMBER": "66", "GITHUB_REPOSITORY": "o/f", "GITHUB_RUN_ID": "9",
               "FACTORY_PAT": "pat", "FACTORY_GH_TOKEN": "tok", "APP_DIR": str(repo.work), "GITHUB_STEP_SUMMARY": str(work / "summary.md")}
        with mock.patch.dict(os.environ, env), mock.patch.object(b, "sh", fake_sh), \
                mock.patch.object(b, "wait_for_revert_deploy", return_value="healthy"), \
                mock.patch.object(b, "record_spend_in_ledger"), mock.patch.object(b, "update_state_issues"):
            code = b.finalize()
        report = json.loads((work / "artifacts" / "build-run-report.json").read_text())
        saved = json.loads((work / "state.json").read_text())
        return code, report, saved, (work / "summary.md").read_text(), gh_calls

    def test_a_failed_run_is_reverted_before_anything_is_reported(self):
        r = Repo()
        code, report, saved, summary, gh_calls = self.run_finalize(r)
        self.assertEqual(code, 1)
        self.assertEqual(report["revert"]["status"], "reverted")
        self.assertEqual(git(r.origin, "diff", "--stat", r.base, "main"), "")  # main is back at the base tree
        self.assertIn("**Revert**: `main` restored to", summary)
        self.assertEqual(report["audit"], [])  # a revert that worked is not an audit finding
        # the post-mortem reads state.json, so the revert and the audit must be saved there
        self.assertEqual(saved["revert"]["status"], "reverted")
        self.assertIn("audit", saved)
        failure_issue = next(c for c in gh_calls if c[:3] == ["gh", "issue", "create"])
        self.assertIn("Revert", Path(failure_issue[failure_issue.index("--body-file") + 1]).read_text())

    def test_an_update_intake_that_failed_loses_its_go_label_and_says_how_to_retry(self):
        _, _, _, _, gh_calls = self.run_finalize(Repo())
        comment = next(c for c in gh_calls if c[:3] == ["gh", "issue", "comment"])
        self.assertIn("add `proceed-with-change` again", comment[comment.index("--body") + 1])
        self.assertTrue(any(c[:3] == ["gh", "issue", "edit"] and "--remove-label" in c for c in gh_calls))

    def test_a_good_ending_and_a_contained_one_are_not_reverted(self):
        for outcome, extra in (("released", {"release": {"released": ["demo.feature.x"]}}), ("watchdog_disabled", {})):
            r = Repo()
            _, report, _, _, _ = self.run_finalize(r, outcome, extra)
            self.assertEqual(report["revert"]["status"], "skipped", outcome)
            self.assertEqual(r.origin_main(), r.head, outcome)

    def test_a_revert_that_could_not_be_done_is_an_audit_finding_and_a_fix_request_requirement(self):
        r = Repo()
        git(r.work, "remote", "set-url", "origin", str(r.tmp / "nowhere.git"))
        _, report, saved, _, _ = self.run_finalize(r)
        self.assertEqual(report["revert"]["status"], "failed")
        self.assertTrue(any(a["rule"].startswith("A-07") for a in report["audit"]))
        facts = pm.collect_facts(tempfile.mkdtemp(), saved)
        self.assertIn("revert failed", fixrequest.requirements(facts, None, saved["revert"])[0])
        lessons = pm.lessons_from(facts)
        self.assertEqual(lessons[0]["kind"], "audit_violation")  # reachable now that state.json carries the audit


class Policy(unittest.TestCase):
    def test_every_bad_ending_gets_a_fix_request_and_good_ones_do_not(self):
        for outcome in ("round_limit", "needs_human", "stuck", "budget_exhausted", "time_limit", "crash", "watchdog_disabled"):
            self.assertTrue(pm.wants_fix_request({"outcome": outcome}, {}), outcome)
        for outcome in ("released", "nothing_to_release", "planned"):
            self.assertFalse(pm.wants_fix_request({"outcome": outcome}, {}), outcome)
        self.assertFalse(pm.wants_fix_request({"outcome": "crash"}, {"fix_requests": False}))

    def test_the_auditor_wants_a_revert_for_a_failed_run_that_pushed(self):
        base = {"outcome": "round_limit", "commits": ["h"], "stages": [], "blocking": []}
        rules = lambda d: [a["rule"][:4] for a in audit.audit_report(d)]
        self.assertEqual(rules(base), ["A-07"])
        self.assertEqual(rules(dict(base, revert={"status": "reverted"})), [])
        self.assertEqual(rules(dict(base, revert={"status": "skipped", "reason": "off"})), [])
        self.assertEqual(rules(dict(base, revert={"status": "failed", "reason": "x"})), ["A-07"])
        self.assertEqual(rules(dict(base, commits=[])), [])
        self.assertNotIn("A-07", [a["rule"][:4] for a in audit.audit_report(dict(base, outcome="watchdog_disabled", release={"released": ["a"]}))])


if __name__ == "__main__":
    unittest.main()
