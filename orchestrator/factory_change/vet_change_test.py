import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_change import vet_change  # noqa: E402

LIMITS = {"factory_change_max_files": 3, "factory_change_max_added_lines": 50}


def change(status="M", added=5, deleted=0):
    return {"status": status, "added": added, "deleted": deleted}


class Vetting(unittest.TestCase):
    def problem(self, changes, patches=None):
        return vet_change.problem(changes, LIMITS, patches)

    def test_a_small_tier_one_change_passes(self):
        self.assertIsNone(self.problem({"orchestrator/bugs/route_bug.py": change(), "orchestrator/bugs/route_bug_test.py": change()}))

    def test_nothing_changed_is_refused(self):
        self.assertIn("nothing", self.problem({}))

    def test_a_protected_path_is_refused(self):
        self.assertIn(".github/workflows/x.yml", self.problem({".github/workflows/x.yml": change()}))
        self.assertIn("pyproject.toml", self.problem({"pyproject.toml": change()}))

    def test_a_change_mixing_tiers_is_refused(self):
        self.assertIn("mixes", self.problem({"orchestrator/bugs/a.py": change(), "orchestrator/try_fix/b.py": change()}))

    def test_too_many_files_or_lines_is_refused(self):
        many = {f"orchestrator/bugs/f{i}.py": change() for i in range(4)}
        self.assertIn("4 files", self.problem(many))
        self.assertIn("60 lines", self.problem({"orchestrator/bugs/a.py": change(added=60)}))

    def test_a_deleted_test_needs_a_replacement(self):
        gone = {"orchestrator/bugs/a_test.py": change("D", 0, 9)}
        self.assertIn("deletes tests", self.problem(gone))
        self.assertIsNone(self.problem({**gone, "orchestrator/bugs/b_test.py": change("A")}))

    def test_raising_a_model_or_a_cap_is_refused(self):
        patch = {"agents/profiles.yml": "+  cost_cap_usd_default: 9.00\n"}
        self.assertIn("spending cap", self.problem({"agents/profiles.yml": change()}, patch))

    def test_emphasis_added_to_a_prompt_is_refused(self):
        patch = {"agents/prompts/coder.md": "+You MUST always check\n"}
        self.assertIn("emphasis", self.problem({"agents/prompts/coder.md": change()}, patch))


if __name__ == "__main__":
    unittest.main()
