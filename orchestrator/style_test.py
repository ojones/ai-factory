# Style rules for the Factory's Python that ruff cannot express (STANDARDS-CODING.md, "Factory Python"). ruff covers the rest.
# Run: python3 -m unittest discover -p "*_test.py" orchestrator
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", "node_modules", "__pycache__", ".claude", ".scratch", ".wayfinder", "templates"}


def python_files():
    return sorted(p for p in ROOT.rglob("*.py") if not SKIP & set(p.relative_to(ROOT).parts))


class FactoryPythonStyle(unittest.TestCase):
    def test_a_test_file_is_named_name_test_not_test_name(self):
        # Discovery only matches *_test.py, so a test_<name>.py would never run.
        bad = [str(p.relative_to(ROOT)) for p in python_files() if p.name.startswith("test_")]
        self.assertEqual(bad, [], "name test files <name>_test.py")
        for p in (ROOT / "orchestrator").glob("*.py"):
            if "test" in p.stem.split("_"):
                self.assertTrue(p.name.endswith("_test.py"), f"{p.name} would not be discovered")

    def test_comments_are_hash_comments_never_docstrings_or_bare_strings(self):
        bad = []
        for p in python_files():
            for node in ast.walk(ast.parse(p.read_text(), str(p))):
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    bad.append(f"{p.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(bad, [], "write a # comment instead of a string statement (docstring)")

    def test_nothing_reads_a_docstring(self):
        bad = [str(p.relative_to(ROOT)) for p in python_files() if p != Path(__file__).resolve() and "__doc__" in p.read_text()]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
