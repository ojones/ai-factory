import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run import endings  # noqa: E402
from build_run.run import BuildRun  # noqa: E402


class CheckProblem(unittest.TestCase):

    def make(self, scripts, exit_code=0, output="src/a.ts(3,1): error TS2322"):
        run = object.__new__(BuildRun)
        run.agent_user = None
        run.app_dir = Path(tempfile.mkdtemp(prefix="check-test-"))
        (run.app_dir / "package.json").write_text(json.dumps({"scripts": scripts}))
        run.restore_tree = lambda *a, **k: None
        bin_dir = Path(tempfile.mkdtemp(prefix="npm-stub-"))
        stub = bin_dir / "npm"
        stub.write_text(f"#!/bin/sh\necho '{output}'\nexit {exit_code}\n")
        stub.chmod(0o755)
        self.patch = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        return run

    def test_a_passing_check_is_no_problem(self):
        self.assertIsNone(self.make({"check": "tsc"}).check_problem())

    def test_a_failing_check_tells_the_coder_the_errors(self):
        problem = self.make({"check": "tsc"}, exit_code=2).check_problem()
        self.assertIn("npm run check", problem)
        self.assertIn("TS2322", problem)

    def test_an_app_without_a_check_script_is_skipped(self):
        self.assertIsNone(self.make({"test": "x"}, exit_code=2).check_problem())


class FoundSecrets(unittest.TestCase):

    def make(self, listed, declared=(), present=()):
        run = object.__new__(BuildRun)
        run.app_repo, run.issue, run.factory_repo, run.factory_token = "o/app", "7", "o/f", "tok"
        run.declared_secrets = [{"name": n, "purpose": "declared"} for n in declared]
        run.state = mock.Mock(d={})
        run.posted = []
        run.git = lambda *a, check=True, cwd=None: mock.Mock(returncode=0, stdout=json.dumps({"secrets": [{"name": n, "purpose": "p"} for n in listed]}))
        run.gh = lambda args, token=None, check=True: self.gh(run, args, present)
        return run

    def gh(self, run, args, present):
        if args[:2] == ["secret", "list"]:
            return mock.Mock(returncode=0, stdout=json.dumps([{"name": n} for n in present]))
        run.posted.append(args[args.index("--body") + 1])
        return mock.Mock(returncode=0, stdout="")

    def test_a_valid_name_the_plan_did_not_declare_is_accepted(self):
        self.assertIsNone(self.make(["EXTRA_API_KEY"]).secret_problem("base", "head"))

    def test_an_invalid_or_factory_name_is_still_rejected(self):
        for bad in ("fly_token", "FLY_API_TOKEN", "GITHUB_TOKEN"):
            self.assertIn(bad, self.make([bad]).secret_problem("base", "head"))

    def test_only_declared_names_need_no_comment_and_no_stop(self):
        run = self.make(["A_KEY"], declared=["A_KEY"])
        run.require_found_secrets("head")
        self.assertEqual(run.posted, [])

    def test_a_found_name_that_is_set_is_recorded_and_the_run_goes_on(self):
        run = self.make(["A_KEY", "B_KEY"], declared=["A_KEY"], present=["A_KEY", "B_KEY"])
        run.require_found_secrets("head")
        self.assertIn("factory-secrets", run.posted[0])
        self.assertIn("B_KEY", run.posted[0])
        self.assertEqual(run.state.d["secrets"], ["A_KEY", "B_KEY"])

    def test_a_found_name_that_is_missing_stops_as_an_owner_wait_with_the_command(self):
        run = self.make(["A_KEY", "B_KEY"], declared=["A_KEY"], present=["A_KEY"])
        with self.assertRaises(endings.AwaitingSecret) as cm:
            run.require_found_secrets("head")
        self.assertIn("B_KEY", str(cm.exception))
        self.assertIn("gh secret set B_KEY -R o/app", run.posted[0])
        self.assertNotIn("gh secret set A_KEY", run.posted[0])
        self.assertIn("B_KEY", run.posted[0].split("factory-secrets:")[1])

    def test_the_check_runs_for_every_accepted_coder_commit_before_review(self):
        run = self.make([])
        run.check_limits = lambda: None
        run.take_usage = lambda: None
        order = []
        run.require_found_secrets = lambda head: order.append("secrets")
        run.state.stage = lambda *a, **k: order.append("stage")
        run.accept_commit("round 1", 0.1, "abc12345")
        self.assertEqual(order[0], "secrets")


if __name__ == "__main__":
    unittest.main()
