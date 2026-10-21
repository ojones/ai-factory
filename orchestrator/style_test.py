# Style rules for the Factory's Python that ruff cannot express (STANDARDS-CODING.md, "Factory Python"). ruff covers the rest.
# Run: python3 -m unittest discover -p "*_test.py" orchestrator
# Baseline: existing long functions and comments are listed in style_baseline.json; new code may not add to them. Tighten with --update, count with --report.
import ast
import io
import json
import sys
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", "node_modules", "__pycache__", ".claude", ".scratch", ".wayfinder", "templates"}
BASELINE = Path(__file__).with_name("style_baseline.json")

# The tunable numbers. A body is the lines from its first statement to its last. Over MAX_LINES fails; over GOAL_LINES is reported by --report.
GOAL_LINES = 5
MAX_LINES = 10
MAX_INDENT = 4
BLOCKS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.For, ast.AsyncFor, ast.While, ast.If, ast.With, ast.AsyncWith, ast.Try)
ALLOWED_COMMENT_MARKERS = ("noqa", "type:", "pragma", "!")


def python_files():
    return sorted(p for p in ROOT.rglob("*.py") if not SKIP & set(p.relative_to(ROOT).parts))


def function_lengths():
    found = {}
    for path in python_files():
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[f"{path.relative_to(ROOT)}::{node.name}"] = max(found.get(f"{path.relative_to(ROOT)}::{node.name}", 0), node.end_lineno - node.body[0].lineno + 1)
    return found


def indent_depth(node, is_elif=False):
    elif_child = node.orelse[0] if isinstance(node, ast.If) and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If) else None
    children = [indent_depth(c, c is elif_child) for c in ast.iter_child_nodes(node)]
    return max(children, default=0) + (isinstance(node, BLOCKS) and not is_elif)


def function_depths():
    found = {}
    for path in python_files():
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = f"{path.relative_to(ROOT)}::{node.name}"
                found[key] = max(found.get(key, 0), indent_depth(node) - 1)
    return found


def comment_counts():
    counts = {}
    for path in python_files():
        tokens = tokenize.generate_tokens(io.StringIO(path.read_text()).readline)
        comments = [t.string for t in tokens if t.type == tokenize.COMMENT and not any(m in t.string for m in ALLOWED_COMMENT_MARKERS)]
        if comments:
            counts[str(path.relative_to(ROOT))] = len(comments)
    return counts


def load_baseline():
    return json.loads(BASELINE.read_text())


def tightened(current, limit, allowed):
    return {name: n for name, n in current.items() if n > limit and (allowed is None or name in allowed)}


def write_baseline():
    old = load_baseline() if BASELINE.exists() else {}
    long_functions = tightened(function_lengths(), MAX_LINES, old.get("long_functions"))
    deep_functions = tightened(function_depths(), MAX_INDENT, old.get("deep_functions"))
    comments = {name: n for name, n in comment_counts().items() if "comments" not in old or name in old["comments"]}
    BASELINE.write_text(json.dumps({"long_functions": long_functions, "deep_functions": deep_functions, "comments": comments}, indent=1, sort_keys=True) + "\n")


def report():
    lengths = function_lengths()
    print(f"functions over {GOAL_LINES} lines: {sum(n > GOAL_LINES for n in lengths.values())} of {len(lengths)}")
    print(f"functions over {MAX_LINES} lines: {sum(n > MAX_LINES for n in lengths.values())}")
    print(f"comments: {sum(comment_counts().values())}")


class FactoryPythonStyle(unittest.TestCase):
    def test_a_test_file_is_named_name_test_not_test_name(self):
        # Discovery only matches *_test.py, so a test_<name>.py would never run.
        bad = [str(p.relative_to(ROOT)) for p in python_files() if p.name.startswith("test_")]
        self.assertEqual(bad, [], "name test files <name>_test.py")
        for p in (ROOT / "orchestrator").rglob("*.py"):
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

    def test_no_new_function_is_over_the_max_and_no_old_one_grows(self):
        allowed = load_baseline()["long_functions"]
        bad = [f"{name} is {n} lines" for name, n in function_lengths().items() if n > MAX_LINES and n > allowed.get(name, MAX_LINES)]
        self.assertEqual(bad, [], f"split it: functions stay under {MAX_LINES} lines (python3 orchestrator/style_test.py --report)")

    def test_no_new_function_nests_deeper_than_the_max_and_no_old_one_deepens(self):
        allowed = load_baseline()["deep_functions"]
        bad = [f"{name} nests {n} deep" for name, n in function_depths().items() if n > MAX_INDENT and n > allowed.get(name, MAX_INDENT)]
        self.assertEqual(bad, [], f"extract a helper: functions nest at most {MAX_INDENT} levels")

    def test_no_file_gains_comments(self):
        allowed = load_baseline()["comments"]
        bad = [f"{name} has {n}" for name, n in comment_counts().items() if n > allowed.get(name, 0)]
        self.assertEqual(bad, [], "name the code so it needs no comment")

    def test_the_baseline_only_shrinks(self):
        lengths, depths, counts, baseline = function_lengths(), function_depths(), comment_counts(), load_baseline()
        stale = [n for n, v in baseline["long_functions"].items() if lengths.get(n, 0) < v] + [n for n, v in baseline["deep_functions"].items() if depths.get(n, 0) < v] + [n for n, v in baseline["comments"].items() if counts.get(n, 0) < v]
        self.assertEqual(stale, [], "progress made: run python3 orchestrator/style_test.py --update to tighten the baseline")


if __name__ == "__main__":
    if "--update" in sys.argv:
        write_baseline()
    elif "--report" in sys.argv:
        report()
    else:
        unittest.main()
