import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import agent_process, http_client  # noqa: E402

from retrospective import agent_run  # noqa: E402


class Isolation(unittest.TestCase):

    def tree(self, files):
        root = Path(tempfile.mkdtemp())
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return root

    def agent_run(self, problems=(), user="agent"):
        factory = self.tree({"agents/a.md": "one", "orchestrator/x.py": "x"})
        facts = self.tree({"facts.json": "{}"}) / "facts.json"
        result = self.tree({}) / "result.json"
        seen = {}

        def fake_watched(cmd, cwd, env, out_path, timeout_s, stall_s, poll=5.0, user=None, pidfile=None):
            seen.update(cmd=cmd, cwd=Path(cwd), env=env, user=user)
            (Path(cwd) / "agents/a.md").write_text("changed by the agent")
            (Path(cwd).parent / "io" / "result.json").write_text('{"category": "prompt_gap"}')
            return 0
        cfg = {"roles": {"retrospective": {"model": "m/x", "prompt": "prompts/retrospective.md"}}, "provider": {"base_url": "https://llm"}}
        with mock.patch.dict(os.environ, {"AGENT_USER": user or "", "BUILD_RUN_DIR": str(self.tree({})), "FACTORY_PAT": "PAT-SECRET",
                                          "DEEPINFRA_API_KEY": "PARENT-KEY", "PATH": os.environ["PATH"]}), \
                mock.patch.object(agent_process, "run_isolation_probes", return_value=list(problems)) as probes, \
                mock.patch.object(agent_process, "run_watched", fake_watched), mock.patch.object(agent_run, "share_with"):
            ran = agent_run.run_agent(factory, cfg, "scoped-key", facts, result, 5)
        return ran, factory, result, seen, probes

    def test_the_agent_runs_as_the_agent_user_in_a_copy_with_a_scrubbed_environment_and_changes_nothing(self):
        ran, factory, result, seen, probes = self.agent_run()
        self.assertTrue(ran)
        probes.assert_called_once_with("agent")
        self.assertEqual(seen["user"], "agent")
        self.assertNotEqual(seen["cwd"], factory)
        self.assertLessEqual(set(seen["env"]), {"PATH", "LANG", "TMPDIR", "CI", "HOME", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "RUNTIME"})
        self.assertEqual(seen["env"]["LLM_API_KEY"], "scoped-key")
        self.assertNotIn("PAT-SECRET", " ".join(seen["env"].values()))
        self.assertNotIn("PARENT-KEY", " ".join(seen["env"].values()))
        self.assertEqual((factory / "agents/a.md").read_text(), "one", msg="what the Agent writes in its copy never reaches the checkout")
        self.assertEqual(json.loads(result.read_text())["category"], "prompt_gap")

    def test_an_isolation_that_cannot_be_proven_means_no_agent_runs(self):
        ran, factory, result, seen, _ = self.agent_run(problems=["an Agent can read the Orchestrator's environment through /proc"])
        self.assertFalse(ran)
        self.assertEqual(seen, {})
        self.assertEqual((factory / "agents/a.md").read_text(), "one")

    def test_without_isolation_it_still_runs_in_a_copy_and_skips_the_probes(self):
        ran, factory, _, seen, probes = self.agent_run(user=None)
        self.assertTrue(ran)
        probes.assert_not_called()
        self.assertIsNone(seen["user"])

class AgentCredential(unittest.TestCase):
    def test_the_agent_gets_a_capped_single_model_credential_never_the_parent_key(self):
        cfg = {"limits": {"retrospective_cost_cap_usd": 0.25, "jwt_ttl_seconds": 100},
               "roles": {"retrospective": {"model": "m/x"}}}
        with mock.patch.object(http_client, "request", return_value=(200, {"token": "jwt-1"})) as http:
            self.assertEqual(agent_run.mint_agent_key(cfg, "parent-key"), "jwt-1")
        _, url, key, body = http.call_args[0]
        self.assertEqual(key, "parent-key")
        self.assertEqual((body["models"], body["spending_limit"]), (["m/x"], 0.25))

    def test_no_credential_means_no_agent_run(self):
        cfg = {"limits": {"jwt_ttl_seconds": 100}, "roles": {"retrospective": {"model": "m/x"}}}
        with mock.patch.object(http_client, "request", return_value=(500, {})):
            self.assertIsNone(agent_run.mint_agent_key(cfg, "parent-key"))


if __name__ == "__main__":
    unittest.main()
