import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import agent_run  # noqa: E402
from shared import github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402
from shared.shell import sh  # noqa: E402

from factory_change import open_pr, pause, protection, review_change, run  # noqa: E402

LIMITS = {"factory_change_max_files": 8, "factory_change_max_added_lines": 400, "factory_change_review_rounds": 2, "max_open_factory_change_prs": 3}
CFG = {"limits": LIMITS, "roles": {"factory_coder": {"prompt": "prompts/factory-coder.md", "model": "m"}}}
TEST = "import unittest\nfrom {pkg}.m import value\n\nclass Case(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(value(), 2)\n"
NAME = "bugs.m_test.Case.test_it"


def factory_repo(pkg="bugs"):
    root = Path(tempfile.mkdtemp())
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "a@b"], ["config", "user.name", "a"]):
        sh(["git", *cmd], cwd=root)
    (root / "orchestrator" / pkg).mkdir(parents=True)
    (root / "orchestrator" / pkg / "m.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    sh(["git", "add", "-A"], cwd=root)
    sh(["git", "commit", "-qm", "base"], cwd=root)
    return root


class Coder:
    agent_user = None

    def __init__(self, value=2, pkg="bugs", name=NAME, write_result=True):
        self.value, self.pkg, self.name, self.write_result = value, pkg, name, write_result
        self.rounds = 0

    def run(self, role, label, prompt, cwd=None, **_):
        self.rounds += 1
        (Path(cwd) / "orchestrator" / self.pkg / "m.py").write_text(f"def value():\n    return {self.value}\n", encoding="utf-8")
        (Path(cwd) / "orchestrator" / self.pkg / "m_test.py").write_text(TEST.format(pkg=self.pkg), encoding="utf-8")
        if self.write_result:
            (Path(cwd).parent / "coder-result.json").write_text(json.dumps({"reproduction": self.name, "summary": "Return two"}), encoding="utf-8")
        return 0, 0.01, None


class Running(unittest.TestCase):
    def setUp(self):
        self.unprotected = None
        self.gh = FakeIssues()
        self.child = self.gh.add(5)
        for target, kw in ((github, {"run": self.gh}), (github, {"ensure_label": mock.Mock()})):
            patcher = mock.patch.multiple(target, **kw)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.opened = mock.Mock(return_value="https://github.com/o/f/pull/9")
        for target, name, value in ((open_pr, "open_pr", self.opened), (agent_run, "run_tests", mock.Mock(return_value=True))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.verdict = (True, [], [])
        patcher = mock.patch.object(protection, "problem", lambda *a: self.unprotected)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(review_change, "review", lambda *a: self.verdict)
        patcher.start()
        self.addCleanup(patcher.stop)

    def go(self, coder, factory=None):
        work = Path(tempfile.mkdtemp())
        return run.ChangeRun("o/f", 5, "pat", CFG, factory or factory_repo(), work, coder, None, "the task").run()

    def test_a_clean_tier_one_change_opens_a_pr_that_merges_itself(self):
        self.assertEqual(self.go(Coder()), "pr_open")
        args = self.opened.call_args.args
        self.assertEqual((args[4], args[5]), ("Return two", NAME))
        self.assertIn("merges itself", self.gh.comments[5][0])

    def test_a_control_path_change_is_held_for_a_person(self):
        factory = factory_repo("try_fix")
        with mock.patch.object(github, "run", self.gh):
            outcome = self.go(Coder(pkg="try_fix", name="try_fix.m_test.Case.test_it"), factory)
        self.assertEqual(outcome, "awaiting_human")
        self.assertIn("control path", self.gh.comments[5][-1])

    def test_a_reproduction_that_does_not_fail_on_main_is_not_accepted(self):
        coder = Coder(value=1)
        self.assertEqual(self.go(coder), "needs_human")
        self.assertEqual(coder.rounds, 2)
        self.opened.assert_not_called()

    def test_blocking_findings_send_the_coder_back_until_the_rounds_run_out(self):
        self.verdict = (False, [{"summary": "bug"}], [])
        coder = Coder()
        self.assertEqual(self.go(coder), "needs_human")
        self.assertEqual(coder.rounds, 2)
        self.opened.assert_not_called()

    def test_a_change_outside_its_scope_is_refused_and_discarded(self):
        factory = factory_repo()
        (factory / ".github").mkdir()
        coder = Coder(pkg="bugs")
        original = coder.run

        def run_and_touch(role, label, prompt, cwd=None, **kw):
            (Path(cwd) / "pyproject.toml").write_text("x", encoding="utf-8")
            return original(role, label, prompt, cwd, **kw)
        coder.run = run_and_touch
        with mock.patch.object(agent_run, "allowed_path", lambda p: True):
            self.assertEqual(self.go(coder, factory), "refused")
        self.assertFalse((factory / "pyproject.toml").exists())

    def test_a_change_that_needs_the_spec_is_queued_for_a_person_and_discarded(self):
        factory = factory_repo()
        coder = Coder()
        original = coder.run

        def run_and_touch(role, label, prompt, cwd=None, **kw):
            (Path(cwd) / "docs").mkdir(exist_ok=True)
            (Path(cwd) / "docs" / "invariants.md").write_text("| INV-99 |", encoding="utf-8")
            return original(role, label, prompt, cwd, **kw)
        coder.run = run_and_touch
        self.assertEqual(self.go(coder, factory), "needs_human")
        self.assertIn("docs/invariants.md", self.gh.comments[5][0])
        self.assertFalse((factory / "docs").exists())
        self.opened.assert_not_called()

    def test_no_branch_protection_means_nothing_starts(self):
        self.unprotected = "branch protection on `main` does not require unit"
        coder = Coder()
        self.assertEqual(self.go(coder), "needs_human")
        self.assertEqual(coder.rounds, 0)

    def test_a_paused_process_runs_nothing(self):
        pause.pause("o/f", "t", "x")
        coder = Coder()
        self.assertEqual(self.go(coder), "paused")
        self.assertEqual(coder.rounds, 0)

    def test_no_result_file_sends_the_coder_back(self):
        coder = Coder(write_result=False)
        self.assertEqual(self.go(coder), "needs_human")
        self.assertEqual(coder.rounds, 2)

    def test_too_many_open_prs_stop_for_a_person(self):
        self.opened.return_value = None
        self.assertEqual(self.go(Coder()), "needs_human")


if __name__ == "__main__":
    unittest.main()
