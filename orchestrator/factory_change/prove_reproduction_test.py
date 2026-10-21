import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_change import prove_reproduction  # noqa: E402


def tree(test_body):
    root = Path(tempfile.mkdtemp())
    (root / "orchestrator").mkdir()
    (root / "orchestrator" / "case_test.py").write_text(f"import unittest\n\nclass Case(unittest.TestCase):\n    def test_it(self):\n        {test_body}\n", encoding="utf-8")
    return root


class Reproduction(unittest.TestCase):
    NAME = "case_test.Case.test_it"

    def test_names_that_could_be_options_or_paths_are_refused(self):
        for bad in ("", "-k", "--help", "../x.y", "case_test", "a b.c"):
            self.assertFalse(prove_reproduction.valid_name(bad), bad)
        self.assertTrue(prove_reproduction.valid_name(self.NAME))

    def test_a_test_that_fails_on_main_is_proven(self):
        self.assertIsNone(prove_reproduction.failure_on_main(tree("self.assertEqual(1, 2)"), self.NAME))

    def test_a_test_that_passes_on_main_is_not_a_reproduction(self):
        self.assertIn("passes on main", prove_reproduction.failure_on_main(tree("pass"), self.NAME))

    def test_a_test_that_does_not_exist_is_not_a_reproduction(self):
        self.assertIn("does not exist", prove_reproduction.failure_on_main(tree("pass"), "case_test.Case.test_gone"))
        self.assertIn("does not exist", prove_reproduction.failure_on_main(tree("pass"), "nothing_test.Case.test_it"))

    def test_the_branch_has_to_pass(self):
        self.assertIsNone(prove_reproduction.pass_on_branch(tree("pass"), self.NAME))
        self.assertIn("still fails", prove_reproduction.pass_on_branch(tree("self.assertEqual(1, 2)"), self.NAME))


if __name__ == "__main__":
    unittest.main()
