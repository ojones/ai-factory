import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
