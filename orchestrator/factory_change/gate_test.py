import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.shell import sh  # noqa: E402

from factory_change import gate, markers, open_pr  # noqa: E402

LIMITS = {"factory_change_max_files": 8, "factory_change_max_added_lines": 400}
TEST = "import unittest\n\nclass Case(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(value(), 2)\n"


def git(root, *args):
    return sh(["git", *args], cwd=root).stdout


def make(module_value, path="orchestrator/bugs"):
    root = Path(tempfile.mkdtemp())
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "a@b"], ["config", "user.name", "a"]):
        git(root, *cmd)
    (root / path).mkdir(parents=True)
    (root / path / "m.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (root / "orchestrator" / "bugs").mkdir(parents=True, exist_ok=True)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "branch", "base")
    (root / path / "m.py").write_text(f"def value():\n    return {module_value}\n", encoding="utf-8")
    (root / "orchestrator" / "bugs" / "m_test.py").write_text("from bugs.m import value\n" + TEST, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "change")
    return root


def body(tier="tier_one", name="bugs.m_test.Case.test_it"):
    return open_pr.pr_body(5, "s", name, tier, ["orchestrator/bugs/m.py"])


class Gate(unittest.TestCase):
    def main_tree(self, head):
        main = Path(tempfile.mkdtemp()) / "main"
        sh(["git", "clone", "-q", str(head), str(main), "--branch", "base"])
        return main

    def test_a_reproduction_that_fails_on_main_and_passes_on_the_branch_is_proven(self):
        head = make(2)
        changes = gate.vet_change.read_changes(head, "base")
        self.assertIsNone(gate.reproduction_problem(self.main_tree(head), head, body(), changes))

    def test_a_change_that_does_not_fix_the_reproduction_is_not_proven(self):
        head = make(3)
        changes = gate.vet_change.read_changes(head, "base")
        self.assertIn("still fails", gate.reproduction_problem(self.main_tree(head), head, body(), changes))

    def test_a_pull_request_with_no_reproduction_is_not_proven(self):
        head = make(2)
        self.assertIn("no valid reproduction", gate.reproduction_problem(self.main_tree(head), head, "no markers", {}))

    def test_a_label_cannot_lie_about_the_tier(self):
        head = make(2)
        self.assertIsNone(gate.tier_problem(head, body("tier_one"), "base"))
        self.assertIn("make it tier_one", gate.tier_problem(head, body("tier_two"), "base"))

    def test_only_a_tier_one_change_within_scope_merges_itself(self):
        self.assertIsNone(self.merge(make(2)))
        self.assertIn("a person merges", self.merge(make(2, "orchestrator/try_fix")))
        self.assertEqual(markers.read(body(), markers.TIER), "tier_one")

    def merge(self, head):
        with mock.patch.object(gate.config, "load", return_value={"limits": LIMITS}):
            return gate.merge_check(head, body(), "base")


if __name__ == "__main__":
    unittest.main()
