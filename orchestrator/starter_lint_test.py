# The Starter Template's custom lint rules, run against the cases in agents/lint-fixtures/cases.json with the real ESLint.
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "templates" / "starter"
ESLINT = STARTER / "node_modules" / ".bin" / "eslint"
FIXTURES = json.loads((ROOT / "agents" / "lint-fixtures" / "cases.json").read_text())
CASES = FIXTURES["cases"]
FLAG_CASES = FIXTURES["flagCases"]
CHECK_FLAGS = STARTER / "scripts" / "check-flags.mjs"


def lint(filename, code):
    p = subprocess.run([str(ESLINT), "--stdin", "--stdin-filename", filename, "-f", "json"], cwd=STARTER, input=code,
                       capture_output=True, text=True, timeout=120)
    return [m["message"] for f in json.loads(p.stdout or "[]") for m in f["messages"] if m.get("ruleId") in ("no-restricted-syntax", "factory/test-asserts", "factory/test-asserts-strongly")]


@unittest.skipUnless(ESLINT.exists(), "the Starter's dependencies are not installed (run npm ci in templates/starter)")
class StarterLintRules(unittest.TestCase):
    def test_every_case_reports_exactly_what_it_expects(self):
        for case in CASES:
            found = lint(case["filename"], case["code"])
            self.assertEqual(len(found), len(case["expect"]), f"{case['name']}: {found}")
            for message, fragment in zip(found, case["expect"]):
                self.assertIn(fragment, message, case["name"])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FlagTestCheck(unittest.TestCase):
    def test_every_flag_case_reports_exactly_what_it_expects(self):
        for case in FLAG_CASES:
            p = subprocess.run(["node", str(CHECK_FLAGS), "--stdin"], input=json.dumps({"slugs": case["slugs"], "files": case["files"]}),
                               capture_output=True, text=True, timeout=60)
            found = json.loads(p.stdout)
            self.assertEqual(len(found), len(case["expect"]), f"{case['name']}: {found}")
            for message, fragment in zip(found, case["expect"]):
                self.assertIn(fragment, message, case["name"])

    def test_the_cases_cover_each_way_to_fail_and_a_clean_pass(self):
        failing = " ".join(f for c in FLAG_CASES for f in c["expect"])
        for fragment in ("no flag-off test", "no flag-on test", "checked in 2 places"):
            self.assertIn(fragment, failing)
        self.assertTrue(any(c["expect"] == [] and c["slugs"] for c in FLAG_CASES))

    def test_npm_run_check_runs_it(self):
        self.assertIn("scripts/check-flags.mjs", json.loads((STARTER / "package.json").read_text())["scripts"]["check"])


class Cases(unittest.TestCase):
    def test_each_custom_rule_has_a_failing_and_a_passing_case(self):
        failing = {fragment for c in CASES for fragment in c["expect"]}
        self.assertLessEqual({"source text", "flags.json", ".only", "makes no assertion", "toBeTruthy/toBeDefined"}, failing)
        self.assertTrue(any(c["expect"] == [] for c in CASES))
        self.assertTrue(any("frontend" in c["filename"] for c in CASES))


if __name__ == "__main__":
    unittest.main()
