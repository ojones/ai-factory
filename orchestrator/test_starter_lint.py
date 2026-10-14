"""The Starter Template's custom lint rules, run against the cases in agents/lint-fixtures/cases.json with the real ESLint."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "templates" / "starter"
ESLINT = STARTER / "node_modules" / ".bin" / "eslint"
CASES = json.loads((ROOT / "agents" / "lint-fixtures" / "cases.json").read_text())["cases"]


def lint(filename, code):
    p = subprocess.run([str(ESLINT), "--stdin", "--stdin-filename", filename, "-f", "json"], cwd=STARTER, input=code,
                       capture_output=True, text=True, timeout=120)
    return [m["message"] for f in json.loads(p.stdout or "[]") for m in f["messages"] if m.get("ruleId") == "no-restricted-syntax"]


@unittest.skipUnless(ESLINT.exists(), "the Starter's dependencies are not installed (run npm ci in templates/starter)")
class StarterLintRules(unittest.TestCase):
    def test_every_case_reports_exactly_what_it_expects(self):
        for case in CASES:
            found = lint(case["filename"], case["code"])
            self.assertEqual(len(found), len(case["expect"]), f"{case['name']}: {found}")
            for message, fragment in zip(found, case["expect"]):
                self.assertIn(fragment, message, case["name"])


class Cases(unittest.TestCase):
    def test_each_custom_rule_has_a_failing_and_a_passing_case(self):
        failing = {fragment for c in CASES for fragment in c["expect"]}
        self.assertLessEqual({"source text", "flags.json", ".only"}, failing)
        self.assertTrue(any(c["expect"] == [] for c in CASES))
        self.assertTrue(any("frontend" in c["filename"] for c in CASES))


if __name__ == "__main__":
    unittest.main()
