import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import agent_process, github  # noqa: E402


class RunWatched(unittest.TestCase):
    def test_stalled_only_after_the_limit_and_never_when_off(self):
        self.assertFalse(agent_process.silent_too_long(100, 150, 60))
        self.assertTrue(agent_process.silent_too_long(100, 160, 60))
        self.assertFalse(agent_process.silent_too_long(0, 10**6, 0))

    def test_a_silent_process_is_killed_as_a_stall_and_a_chatty_one_finishes(self):
        out = Path(tempfile.mkdtemp()) / "o.jsonl"
        started = time.time()
        rc = agent_process.run_watched([sys.executable, "-c", "import time; time.sleep(60)"], None, os.environ.copy(), out, 30, 1, poll=0.2)
        self.assertEqual(rc, "stall")
        self.assertLess(time.time() - started, 10)
        rc = agent_process.run_watched([sys.executable, "-c", "import time\nfor i in range(6):\n print(i, flush=True); time.sleep(0.4)"],
                           None, os.environ.copy(), out, 30, 1.5, poll=0.2)
        self.assertEqual(rc, 0)
        rc = agent_process.run_watched([sys.executable, "-c", "import time\nwhile True:\n print('x', flush=True); time.sleep(0.2)"],
                           None, os.environ.copy(), out, 1, 5, poll=0.2)
        self.assertEqual(rc, "timeout")


class AgentIsolation(unittest.TestCase):
    def test_without_a_user_the_command_is_unchanged(self):
        self.assertEqual(agent_process.agent_command(["openhands", "-t", "x"], {"PATH": "/bin"}, None), ["openhands", "-t", "x"])

    def test_with_a_user_variables_go_by_name_and_never_by_value(self):
        env = {"PATH": "/opt/bin", "LLM_API_KEY": "jwt-secret-value", "HOME": "/srv/agent/run/home-a"}
        cmd = agent_process.agent_command(["openhands", "-t", "x"], env, "agent", "/srv/agent/run/pgid.txt")
        self.assertEqual(cmd[:5], ["sudo", "-n", "-u", "agent", "--preserve-env=LLM_API_KEY,HOME"])
        self.assertNotIn("jwt-secret-value", " ".join(cmd))
        self.assertIn("PATH=/opt/bin", cmd)
        self.assertEqual(cmd[-3:], ["openhands", "-t", "x"])
        self.assertIn("/srv/agent/run/pgid.txt", cmd)

    def test_the_git_credential_travels_in_the_environment_not_the_arguments(self):
        env = github.git_auth_env("Authorization: Basic abc")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "http.extraheader")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "Authorization: Basic abc")

    def test_the_self_check_finds_each_way_isolation_can_fail(self):
        good = {"whoami": "agent\n", "environ": "", "workspace": "", "env_names": "", "sudo": "no\n"}
        self.assertEqual(agent_process.isolation_problems(good), [])
        for bad, text in (({"whoami": "runner\n"}, "different account"), ({"environ": "ISOLATION_MARK=SELF-CHECK-SECRET"}, "environment"),
                          ({"workspace": "app\nrun"}, "workspace"), ({"env_names": "FACTORY_PAT\n"}, "credential"), ({"sudo": "yes\n"}, "sudo")):
            problems = agent_process.isolation_problems({**good, **bad})
            self.assertEqual(len(problems), 1)
            self.assertIn(text, problems[0])


if __name__ == "__main__":
    unittest.main()
