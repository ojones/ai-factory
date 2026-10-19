# Tests for template sync. Run: python3 -m unittest discover -p "*_test.py" orchestrator
import unittest

from maintenance import template_sync as t

T = "a" * 40
BASE = "b" * 40


class Changes(unittest.TestCase):
    def test_name_status_loses_the_template_prefix_and_follows_renames(self):
        text = "M\ttemplates/starter/package.json\nA\ttemplates/starter/eslint.config.mjs\nR100\ttemplates/starter/a.ts\ttemplates/starter/b.ts"
        self.assertEqual(t.parse_name_status(text), [("M", "package.json"), ("A", "eslint.config.mjs"), ("R", "b.ts")])

    def test_protected_and_lock_files_are_not_applied(self):
        changes = [("M", "package.json"), ("M", "package-lock.json"), ("M", "fly.toml"), ("M", ".github/workflows/ci.yml"),
                   ("M", "backend/src/feature-flags.ts"), ("A", "eslint.config.mjs")]
        applicable, protected, ignored = t.split_changes(changes)
        self.assertEqual([p for _, p in applicable], ["package.json"])  # the lint config is the Orchestrator's, not the coder's
        self.assertEqual(sorted(protected), [".github/workflows/ci.yml", "backend/src/feature-flags.ts", "fly.toml"])
        self.assertEqual(ignored, ["package-lock.json"])
        self.assertEqual(t.orchestrator_applied(changes), ["eslint.config.mjs"])

    def test_files_the_build_run_copies_itself_are_in_no_agent_list(self):
        changes = [("M", ".github/dependabot.yml"), ("M", ".github/workflows/test-gate.yml"), ("M", ".github/workflows/build.yml"), ("M", "package.json")]
        applicable, protected, _ = t.split_changes(changes)
        self.assertEqual([p for _, p in applicable], ["package.json"])
        self.assertEqual(protected, [".github/workflows/build.yml"])
        self.assertEqual(t.orchestrator_applied(changes), [".github/dependabot.yml", ".github/workflows/test-gate.yml"])
        self.assertIn("Already applied by the Orchestrator", t.sync_request("a", T, BASE, [], [], "", [".github/dependabot.yml"]))

    def test_only_a_full_sha_is_a_stamp(self):
        self.assertEqual(t.stamp_value(T + "\n"), T)
        for bad in ("", "abc123", "not a sha", T + "x"):
            self.assertIsNone(t.stamp_value(bad))


class Decide(unittest.TestCase):
    ap = [("M", "package.json")]

    def test_files_when_behind_with_something_to_apply(self):
        self.assertTrue(t.should_sync(self.ap, T, BASE, [], [], "app"))

    def test_not_when_nothing_applies_or_already_current_or_one_is_open(self):
        self.assertFalse(t.should_sync([], T, BASE, [], [], "app"))
        self.assertFalse(t.should_sync(self.ap, T, T, [], [], "app"))
        self.assertFalse(t.should_sync(self.ap, T, BASE, [], [{"number": 1}], "app"))

    def test_a_target_already_filed_is_not_filed_again_even_if_it_failed(self):
        self.assertFalse(t.should_sync(self.ap, T, BASE, [f"app: template sync [sync {T[:7]}]"], [], "app"))
        self.assertTrue(t.should_sync(self.ap, T, BASE, ["app: template sync [sync 1234567]"], [], "app"))


class Request(unittest.TestCase):
    def test_the_request_names_files_protected_ones_the_stamp_and_the_diff(self):
        text = t.sync_request("todo", T, BASE, [("A", "eslint.config.mjs")], ["fly.toml"], "+rule")
        for needle in ("eslint.config.mjs", "`fly.toml`", f"`{T}` to a file named `{t.STAMP}`", "+rule", "no feature flag"):
            self.assertIn(needle, text)

    def test_a_huge_diff_is_clipped(self):
        text = t.sync_request("todo", T, BASE, [("M", "a")], [], "x" * 50000)
        self.assertIn("clipped", text)
        self.assertLess(len(text), 25000)


if __name__ == "__main__":
    unittest.main()
