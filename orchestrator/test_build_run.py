"""Unit tests for the Build Run's deterministic logic. Run: python3 -m unittest discover orchestrator"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402

FORM = ("### What should be built?\r\n\r\nA notes app\r\nwith tags\r\n\r\n"
        "### Cost cap override (USD)\r\n\r\n{cap}\r\n")


class Intake(unittest.TestCase):
    def test_default_cap(self):
        task, cap = b.parse_intake(FORM.format(cap="_No response_"), 2.0, 10.0)
        self.assertEqual((task, cap), ("A notes app\nwith tags", 2.0))

    def test_override_with_dollar_sign(self):
        self.assertEqual(b.parse_intake(FORM.format(cap="$3.5"), 2.0, 10.0)[1], 3.5)

    def test_rejects_over_ceiling_zero_and_garbage(self):
        for bad in ("10.01", "0", "abc"):
            with self.assertRaises(b.NeedsHuman):
                b.parse_intake(FORM.format(cap=bad), 2.0, 10.0)

    def test_rejects_empty_task(self):
        with self.assertRaises(b.NeedsHuman):
            b.parse_intake("### What should be built?\n\n_No response_\n", 2.0, 10.0)


class Verdicts(unittest.TestCase):
    def test_model_verdict_field_is_ignored(self):
        doc = {"verdict": "clean", "findings": [{"severity": "blocking", "summary": "x"}]}
        clean, blocking, _ = b.derive_review(doc)
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)

    def test_minor_only_is_clean(self):
        self.assertTrue(b.derive_review({"findings": [{"severity": "minor"}]})[0])

    def test_review_without_findings_list_is_invalid(self):
        with self.assertRaises(ValueError):
            b.derive_review({"verdict": "clean"})

    def test_tester_passed_is_derived_and_flags_need_coverage(self):
        doc = {"passed": True, "results": [{"flag": "a", "check": "x", "passed": True}]}
        self.assertTrue(b.derive_test(doc, ["a"])[0])
        passed, failures = b.derive_test(doc, ["a", "b"])
        self.assertFalse(passed)
        self.assertEqual(failures[0]["flag"], "b")

    def test_tester_one_failure_fails(self):
        doc = {"passed": True, "results": [{"flag": "a", "passed": True}, {"flag": "a", "passed": False}]}
        self.assertFalse(b.derive_test(doc, ["a"])[0])

    def test_empty_results_with_flags_fails(self):
        self.assertFalse(b.derive_test({"results": []}, ["a"])[0])


class Flags(unittest.TestCase):
    def test_new_slugs_only(self):
        base = '[{"slug":"a","description":"."}]'
        head = '[{"slug":"a","description":"."},{"slug":"b","description":"."}]'
        self.assertEqual(b.new_flag_slugs(base, head), ["b"])

    def test_missing_base_or_garbage(self):
        self.assertEqual(b.new_flag_slugs("", '[{"slug":"a"}]'), ["a"])
        self.assertEqual(b.new_flag_slugs("[]", "not json"), [])

    def test_slug_pattern(self):
        for ok in ("todos-crud", "a1"):
            self.assertTrue(b.SLUG_RE.fullmatch(ok))
        for bad in ("../x", "A", "a b", "", "-a", "a/b"):
            self.assertFalse(b.SLUG_RE.fullmatch(bad))


class Guards(unittest.TestCase):
    def test_protected_paths(self):
        bad = b.protected_violations([".github/workflows/deploy-fly.yml", "fly.toml", "fly/provision.sh",
                                      "backend/src/feature-flags.ts", "INTAKE.md", "backend/src/app.ts",
                                      "flags.json", "backend/src/routes/notes.ts"])
        self.assertEqual(len(bad), 5)
        self.assertNotIn("flags.json", bad)

    def test_release_gate_needs_all_four_on_the_same_sha(self):
        self.assertTrue(b.release_gate(True, True, True, True, "abc", "abc"))
        for i in range(4):
            args = [True] * 4
            args[i] = False
            self.assertFalse(b.release_gate(*args, "abc", "abc"))
        self.assertFalse(b.release_gate(True, True, True, True, "abc", "def"))

    def test_render_replaces_and_rejects_leftovers(self):
        self.assertEqual(b.render("hi {{a}} {{a}}", {"a": 1}), "hi 1 1")
        with self.assertRaises(ValueError):
            b.render("hi {{a}} {{b}}", {"a": 1})


class Prompts(unittest.TestCase):
    """Every role prompt's placeholders are exactly the ones the orchestrator supplies."""
    SUPPLIED = {
        "coder": {"app_name", "round", "task", "findings_path"},
        "reviewer": {"app_name", "base_sha", "head_sha", "verdict_path"},
        "tester": {"app_name", "app_url", "head_sha", "report_path"},
        "pipeline": {"app_name", "head_sha", "failure_run_url", "diagnosis_path", "context_dir"},
    }

    def test_placeholders(self):
        import re
        for role, supplied in self.SUPPLIED.items():
            text = (b.FACTORY_DIR / "agents" / "prompts" / f"{role}.md").read_text()
            self.assertEqual(set(re.findall(r"\{\{(\w+)\}\}", text)) - supplied, set(), role)


class PreviewToken(unittest.TestCase):
    def test_matches_the_shell_script_that_app_staging_uses(self):
        shell = subprocess.run([str(b.FACTORY_DIR / "infra/app-staging/preview-token.sh"), "demo-app"],
                               env={**os.environ, "PREVIEW_MASTER_SECRET": "x"}, capture_output=True, text=True)
        self.assertEqual(shell.stdout.strip(), b.preview_token("x", "demo-app"))


class BudgetAccounting(unittest.TestCase):
    def setUp(self):
        self.calls, self.spend = [], {}
        self._orig = b.http

        def fake(method, url, token=None, body=None, timeout=60):
            self.calls.append((method, body))
            if method == "POST":
                jwt = f"jwt{len(self.calls)}"
                self.spend[jwt] = 0.0
                return 200, {"token": jwt}
            return 200, {"spending_current": self.spend[url.split("jwtoken=")[1]]}
        b.http = fake

    def tearDown(self):
        b.http = self._orig

    def test_each_jwt_is_single_model_and_limited_to_what_is_left(self):
        bud = b.Budget("admin", 2.0, 100)
        j1 = bud.mint("m1")
        self.spend[j1] = 0.75
        self.assertAlmostEqual(bud.refresh(j1), 0.75)
        bud.mint("m2")
        post = [c[1] for c in self.calls if c[0] == "POST"]
        self.assertEqual([p["models"] for p in post], [["m1"], ["m2"]])
        self.assertEqual([p["spending_limit"] for p in post], [2.0, 1.25])

    def test_spend_sums_across_jwts_and_exhaustion_stops_minting(self):
        bud = b.Budget("admin", 1.0, 100)
        j1 = bud.mint("m1")
        self.spend[j1] = 0.6
        bud.refresh(j1)
        j2 = bud.mint("m2")
        self.spend[j2] = 0.45  # the crossing call completes, so overshoot is allowed
        self.assertAlmostEqual(bud.refresh(j2), 1.05)
        with self.assertRaises(b.BudgetExhausted):
            bud.mint("m1")


if __name__ == "__main__":
    unittest.main()
