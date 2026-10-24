import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from build_run import endings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import run_stops  # noqa: E402

from build_run.run import BuildRun  # noqa: E402


class WaitForDeploy(unittest.TestCase):
    def make(self, runs, skipped_ids):
        run = object.__new__(BuildRun)
        run.app_repo, run.lim = "o/app", {"pipeline_timeout_minutes": 1}
        run.check_limits = lambda: None
        run.gh = lambda args, check=True: mock.Mock(stdout=json.dumps(runs))
        run.deploy_skipped = lambda rid: rid in skipped_ids
        return run

    def test_a_skipped_deploy_run_is_not_the_deploy(self):
        done = lambda i, sha="s": {"databaseId": i, "headSha": sha, "status": "completed", "conclusion": "success", "url": ""}
        run = self.make([done(1), {**done(2), "status": "in_progress", "conclusion": ""}], {1})
        with mock.patch.object(time, "sleep", side_effect=RuntimeError("kept waiting")):
            with self.assertRaises(RuntimeError):
                run.wait_run("deploy-fly.yml", "s")
        self.assertEqual(self.make([done(1), done(2)], {1}).wait_run("deploy-fly.yml", "s")["databaseId"], 2)

    def test_other_workflows_are_not_filtered(self):
        done = {"databaseId": 1, "headSha": "s", "status": "completed", "conclusion": "success", "url": ""}
        self.assertEqual(self.make([done], {1}).wait_run("build.yml", "s")["databaseId"], 1)


class PipelineNotStarted(unittest.TestCase):
    def test_a_run_github_never_started_stops_without_calling_the_pipeline_agent(self):
        run = object.__new__(BuildRun)
        run.lim = {"pipeline_retries": 2}
        run.wait_run = lambda wf, sha: {"conclusion": "action_required", "url": "https://x/runs/9", "databaseId": 9}
        run.agent_json = lambda *a, **k: self.fail("the Pipeline Agent must not be paid to read a log that does not exist")
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.pipeline("a" * 40)
        self.assertIn("did not start", str(cm.exception))
        self.assertIn("https://x/runs/9", str(cm.exception))


class Diagnosis(unittest.TestCase):
    def make(self, runs, diagnoses, retries=2, rounds=3, healthy=True):
        run = object.__new__(BuildRun)
        run.lim, run.coder_rounds = {"pipeline_retries": retries, "review_rounds": rounds}, 1
        run.app_repo, run.work = "o/app", Path(tempfile.mkdtemp())
        self.runs, self.diagnoses, self.calls, self.coded, self.reruns = list(runs), list(diagnoses), [], [], []
        run.wait_run = lambda wf, sha: self.runs.pop(0) if self.runs else {"conclusion": "success", "url": "u", "databaseId": 1}
        run.healthy = lambda: healthy
        run.failure_context = lambda failed, sha, n: run.work
        run.state = mock.Mock()

        def agent_json(role, label, values, path, check=None):
            self.calls.append((role, label))
            doc = self.diagnoses.pop(0)
            Path(path).write_text(json.dumps(doc), encoding="utf-8")
            return doc, 0.01, {}
        run.agent_json = agent_json
        run.gh = lambda args, check=True: self.reruns.append(args) or mock.Mock(stdout="")
        run.coder = lambda label, request, findings: self.coded.append((label, request)) or "local-fix"
        return run

    def red(self, n=1):
        return {"conclusion": "failure", "url": f"https://x/runs/{n}", "databaseId": n}

    def test_a_green_pipeline_costs_no_diagnosis_and_returns_the_deployed_sha(self):
        run = self.make([], [])
        self.assertEqual(run.pipeline("a" * 40), "a" * 40)
        self.assertEqual(self.calls, [])

    def test_a_flaky_failure_is_re_run_and_then_passes(self):
        run = self.make([self.red(7)], [{"category": "flaky", "retry_recommended": True, "summary": "network"}])
        with mock.patch.object(time, "sleep"):
            self.assertEqual(run.pipeline("a" * 40), "a" * 40)
        self.assertEqual(self.calls, [("pipeline", "p1")])
        self.assertEqual(self.reruns[0][:3], ["run", "rerun", "7"])
        self.assertIn("--failed", self.reruns[0])

    def test_retries_are_bounded_and_then_a_person_decides(self):
        flaky = {"category": "infra", "retry_recommended": True, "summary": "runner lost"}
        run = self.make([self.red(1), self.red(2)], [flaky, flaky], retries=1)
        with mock.patch.object(time, "sleep"), self.assertRaises(run_stops.NeedsHuman) as cm:
            run.pipeline("a" * 40)
        self.assertEqual(len(self.reruns), 1, msg="one re-run, then the second diagnosis stopped it")
        self.assertIn("infra", str(cm.exception))

    def test_a_failure_in_the_code_goes_back_to_the_coder_with_the_agents_fix_request(self):
        run = self.make([self.red()], [{"category": "code", "fix_request": "the lint step fails on app.ts", "summary": "lint"}])
        with self.assertRaises(endings.PipelineFix):
            run.pipeline("a" * 40)
        self.assertEqual(self.coded[0][1], "the lint step fails on app.ts")

    def test_coder_fixes_count_against_the_review_rounds(self):
        run = self.make([self.red(), self.red()], [{"category": "code", "fix_request": "x", "summary": "s"}] * 2, rounds=2)
        with self.assertRaises(endings.PipelineFix):
            run.pipeline("a" * 40)
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.pipeline("b" * 40)
        self.assertEqual(len(self.coded), 1)
        self.assertIn("code", str(cm.exception))

    def test_a_workflow_problem_or_a_code_failure_with_no_fix_request_stops_for_a_person(self):
        for doc in ({"category": "workflow", "summary": "the deploy workflow is missing a secret"}, {"category": "code", "summary": "unclear"}):
            run = self.make([self.red()], [doc])
            with self.assertRaises(run_stops.NeedsHuman):
                run.pipeline("a" * 40)
            self.assertEqual((self.coded, self.reruns), ([], []))

    def test_a_failed_health_check_is_diagnosed_from_the_apps_actions_page(self):
        run = self.make([], [{"category": "workflow", "summary": "the app never answered"}], healthy=False)
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.pipeline("a" * 40)
        self.assertIn("Health check", str(cm.exception))
        self.assertEqual(self.calls, [("pipeline", "p1")])


if __name__ == "__main__":
    unittest.main()
