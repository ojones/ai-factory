import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import agent_process, http_client  # noqa: E402

from retrospective import agent_run, learning_pr, tracker  # noqa: E402


class Paths(unittest.TestCase):
    def test_only_prompts_template_orchestrator_and_docs_are_allowed(self):
        for ok in ("agents/prompts/coder.md", "templates/starter/AGENTS.md", "orchestrator/build_run.py", "STANDARDS.md"):
            self.assertTrue(agent_run.allowed_path(ok), ok)
        for bad in (".github/workflows/build-run.yml", "templates/starter/.github/workflows/build.yml",
                    "templates/starter/fly/provision.sh", "templates/starter/fly.toml", "README.md",
                    "agents/../.github/x.yml"):
            self.assertFalse(agent_run.allowed_path(bad), bad)


class Isolation(unittest.TestCase):
    # The retrospective Agent runs in a copy of the tree as the Agent user, and only allowed files come back.

    def tree(self, files):
        root = Path(tempfile.mkdtemp())
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return root

    def test_changes_are_found_by_comparing_plain_trees_and_git_is_never_read(self):
        before = self.tree({"agents/a.md": "one", "orchestrator/x.py": "x", ".git/config": "[core]\n"})
        after = self.tree({"agents/a.md": "two", "orchestrator/y.py": "y", ".git/config": "[core]\n\tfsmonitor = evil\n"})
        os.symlink("/etc/passwd", after / "templates-link")
        changes, links = agent_run.tree_changes(before, after)
        self.assertEqual(changes, {"agents/a.md": "M", "orchestrator/y.py": "A", "orchestrator/x.py": "D"})
        self.assertEqual(links, ["templates-link"])  # the .git difference is invisible, a symlink is reported and never followed

    def test_only_allowed_paths_are_carried_into_the_checkout_git_runs_in(self):
        before = self.tree({"agents/a.md": "one", "orchestrator/x.py": "x", ".github/workflows/w.yml": "w"})
        after = self.tree({"agents/a.md": "two", ".github/workflows/w.yml": "pwned", ".github/workflows/new.yml": "n",
                           "orchestrator/new_test.py": "t", "docs/huge.md": "x" * (agent_run.MAX_FILE_BYTES + 1), "agents/huge.md": "x" * (agent_run.MAX_FILE_BYTES + 1)})
        changes, _ = agent_run.tree_changes(before, after)
        applied = agent_run.apply_changes(before, after, changes)
        self.assertEqual(sorted(applied), ["agents/a.md", "orchestrator/new_test.py", "orchestrator/x.py"])
        self.assertEqual((before / "agents/a.md").read_text(), "two")
        self.assertEqual((before / ".github/workflows/w.yml").read_text(), "w")  # a workflow is never touched
        self.assertFalse((before / ".github/workflows/new.yml").exists())
        self.assertFalse((before / "agents/huge.md").exists())  # too big to be a prompt or a rule
        self.assertFalse((before / "orchestrator/x.py").exists())  # a deletion inside an allowed path is carried over

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

    def test_the_agent_runs_as_the_agent_user_in_a_copy_with_a_scrubbed_environment(self):
        ran, factory, result, seen, probes = self.agent_run()
        self.assertTrue(ran)
        probes.assert_called_once_with("agent")
        self.assertEqual(seen["user"], "agent")
        self.assertNotEqual(seen["cwd"], factory)
        self.assertLessEqual(set(seen["env"]), {"PATH", "LANG", "TMPDIR", "CI", "HOME", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "RUNTIME"})
        self.assertEqual(seen["env"]["LLM_API_KEY"], "scoped-key")
        self.assertNotIn("PAT-SECRET", " ".join(seen["env"].values()))
        self.assertNotIn("PARENT-KEY", " ".join(seen["env"].values()))
        self.assertEqual((factory / "agents/a.md").read_text(), "changed by the agent")  # an allowed change came back
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

    def test_the_unit_tests_run_as_the_agent_user_in_a_copy_with_no_credential(self):
        factory = self.tree({"orchestrator/x_test.py": "pass"})
        root = self.tree({})
        seen = {}

        def fake_watched(cmd, cwd, env, out_path, timeout_s, stall_s, poll=5.0, user=None, pidfile=None):
            seen.update(cmd=cmd, cwd=Path(cwd), env=env, user=user)
            return 0
        with mock.patch.dict(os.environ, {"FACTORY_PAT": "PAT-SECRET", "DEEPINFRA_API_KEY": "PARENT-KEY", "FACTORY_GH_TOKEN": "tok", "PATH": os.environ["PATH"]}), \
                mock.patch.object(agent_process, "run_watched", fake_watched), mock.patch.object(agent_run, "share_with"):
            self.assertTrue(agent_run.run_tests(factory, root, "agent"))
        self.assertEqual(seen["user"], "agent")
        self.assertNotEqual(seen["cwd"], factory)
        self.assertLessEqual(set(seen["env"]), {"PATH", "LANG", "CI", "HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE"})
        joined = " ".join(seen["env"].values())
        for secret in ("PAT-SECRET", "PARENT-KEY", "tok"):
            self.assertNotIn(secret, joined)
        self.assertFalse((seen["cwd"] / ".git").exists())

    def test_propose_does_nothing_more_when_no_agent_ran(self):
        with mock.patch.object(agent_run, "mint_agent", return_value=("k", object())), mock.patch.object(agent_run, "run_agent", return_value=False), \
                mock.patch.object(agent_run, "record_agent_spend"), mock.patch.object(learning_pr, "open_pr") as open_pr, mock.patch.object(tracker, "gh") as gh:
            result = learning_pr.propose(Path("."), {"limits": {}}, "o/f", "pat", "tok", "parent", Path("f"), Path(tempfile.mkdtemp()) / "r.json", [1], "9")
        self.assertIsNone(result)
        open_pr.assert_not_called()
        gh.assert_not_called()


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
