import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run.run import BuildRun  # noqa: E402


class CheckProblem(unittest.TestCase):
    # The Orchestrator's own `npm run check` on the coder's commit, before the reviewer.

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


if __name__ == "__main__":
    unittest.main()
