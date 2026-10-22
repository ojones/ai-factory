import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github, shell  # noqa: E402


def expire(*args, **kwargs):
    raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])


class DefaultTimeout(unittest.TestCase):
    def test_a_hung_command_becomes_a_failed_result_not_a_hang(self):
        with mock.patch.object(shell.subprocess, "run", side_effect=expire) as ran:
            p = shell.sh(["git", "fetch"], check=False)
        self.assertEqual(ran.call_args.kwargs["timeout"], shell.DEFAULT_TIMEOUT)
        self.assertEqual(p.returncode, shell.TIMED_OUT)
        self.assertIn("timed out", p.stderr)

    def test_a_hung_command_that_must_succeed_raises(self):
        with mock.patch.object(shell.subprocess, "run", side_effect=expire), self.assertRaises(RuntimeError) as cm:
            shell.sh(["git", "push"])
        self.assertIn("timed out", str(cm.exception))

    def test_an_explicit_timeout_still_raises_for_its_caller_to_handle(self):
        with mock.patch.object(shell.subprocess, "run", side_effect=expire), self.assertRaises(subprocess.TimeoutExpired):
            shell.sh(["flyctl", "logs"], check=False, timeout=5)

    def test_gh_calls_are_bounded_too(self):
        with mock.patch.object(shell.subprocess, "run", side_effect=expire):
            p = github.run(["issue", "list"], "t")
            self.assertEqual(p.returncode, shell.TIMED_OUT)
            with self.assertRaises(RuntimeError):
                github.run(["issue", "list"], "t", check=True)


if __name__ == "__main__":
    unittest.main()
