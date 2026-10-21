import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config  # noqa: E402

from factory_change import write_change  # noqa: E402

CFG = {"roles": {"factory_coder": {"prompt": "prompts/factory-coder.md", "model": "m"}}}


class FakeRunner:
    agent_user = None

    def __init__(self, edit):
        self.edit, self.calls = edit, []

    def run(self, role, label, prompt, cwd=None, **_):
        self.calls.append((role, label, prompt, cwd))
        self.edit(Path(cwd), Path(prompt.split("`")[1]) if "`" in prompt else None)
        return 0, 0.01, None


def factory_tree():
    root = Path(tempfile.mkdtemp())
    (root / "orchestrator" / "bugs").mkdir(parents=True)
    (root / "orchestrator" / "bugs" / "a.py").write_text("X = 1\n", encoding="utf-8")
    (root / ".git").mkdir()
    return root


class Coding(unittest.TestCase):
    def setUp(self):
        self.factory, self.work = factory_tree(), Path(tempfile.mkdtemp())

    def run_coder(self, edit, round_no=1, blocking=()):
        runner = FakeRunner(edit)
        got = write_change.write_change(CFG, runner, self.factory, self.work, "do the thing", round_no, blocking)
        return got, runner

    def test_the_coder_works_in_a_copy_and_only_allowed_changes_come_back(self):
        def edit(scratch, _):
            (scratch / "orchestrator" / "bugs" / "a.py").write_text("X = 2\n", encoding="utf-8")
            (scratch / ".github").mkdir()
            (scratch / ".github" / "w.yml").write_text("x", encoding="utf-8")
            (self.work / "coder-result.json").write_text(json.dumps({"reproduction": "bugs.a_test.A.test_x", "summary": "s"}), encoding="utf-8")
        got, runner = self.run_coder(edit)
        self.assertEqual(got["reproduction"], "bugs.a_test.A.test_x")
        self.assertEqual((self.factory / "orchestrator" / "bugs" / "a.py").read_text(encoding="utf-8"), "X = 2\n")
        self.assertFalse((self.factory / ".github").exists())
        self.assertNotEqual(runner.calls[0][3], self.factory)
        self.assertIn("do the thing", runner.calls[0][2])

    def test_no_result_file_means_no_reproduction_was_named(self):
        got, _ = self.run_coder(lambda scratch, _: None)
        self.assertIsNone(got)

    def test_blocking_findings_reach_the_next_round_through_a_file(self):
        self.run_coder(lambda scratch, _: None, 2, [{"summary": "bad"}])
        self.assertEqual(json.loads((self.work / "findings.json").read_text(encoding="utf-8"))["blocking"], [{"summary": "bad"}])

    def test_the_prompt_is_the_one_in_the_repo(self):
        self.assertTrue((config.FACTORY_DIR / "agents" / "prompts" / "factory-coder.md").is_file())


if __name__ == "__main__":
    unittest.main()
