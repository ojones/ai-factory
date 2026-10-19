import os
import unittest
from unittest import mock

from shared import github


def completed(returncode=0, stdout="", stderr=""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


class Run(unittest.TestCase):
    def test_it_runs_gh_with_the_token_it_was_given_not_the_one_in_the_environment(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "actions-token"}), mock.patch("subprocess.run", return_value=completed()) as run:
            github.run(["issue", "view", "7"], "the-pat")
        cmd, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertEqual(cmd, ["gh", "issue", "view", "7"])
        self.assertEqual(kwargs["env"]["GH_TOKEN"], "the-pat")
        self.assertTrue(kwargs["capture_output"] and kwargs["text"])

    def test_a_failure_is_returned_not_raised_unless_the_caller_asks(self):
        with mock.patch("subprocess.run", return_value=completed(1, stderr="boom")):
            self.assertEqual(github.run(["issue", "view", "7"], "t").returncode, 1)
            with self.assertRaisesRegex(RuntimeError, "gh issue view 7 failed: boom"):
                github.run(["issue", "view", "7"], "t", check=True)

    def test_ensure_label_creates_it_in_the_repo_and_ignores_that_it_exists(self):
        with mock.patch("subprocess.run", return_value=completed(1, stderr="already exists")) as run:
            github.ensure_label("o/r", "bug", "t", "d73a4a", "Not working")
        self.assertEqual(run.call_args[0][0], ["gh", "label", "create", "bug", "--repo", "o/r", "--color", "d73a4a", "--description", "Not working"])


if __name__ == "__main__":
    unittest.main()
