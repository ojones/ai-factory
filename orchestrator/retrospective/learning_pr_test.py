import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config  # noqa: E402

from retrospective import learning_pr  # noqa: E402


class MergePolicy(unittest.TestCase):
    def test_only_additive_lint_and_formatter_config_auto_merges(self):
        self.assertTrue(learning_pr.auto_merge_eligible("3\t0\ttemplates/starter/.eslintrc.json\n1\t0\ttemplates/starter/.prettierrc"))
        self.assertTrue(learning_pr.auto_merge_eligible("2\t0\ttemplates/starter/eslint.config.mjs"))

    def test_any_deletion_other_file_or_doubt_means_a_human(self):
        self.assertFalse(learning_pr.auto_merge_eligible("3\t1\ttemplates/starter/.eslintrc.json"))
        self.assertFalse(learning_pr.auto_merge_eligible("3\t0\ttemplates/starter/.eslintrc.json\n1\t0\tagents/prompts/coder.md"))
        self.assertFalse(learning_pr.auto_merge_eligible("3\t0\ttemplates/starter/package.json"))
        self.assertFalse(learning_pr.auto_merge_eligible("3\t0\ttemplates/starter/sub/.eslintrc.json"))
        self.assertFalse(learning_pr.auto_merge_eligible("-\t-\ttemplates/starter/.prettierrc"))
        self.assertFalse(learning_pr.auto_merge_eligible("garbage"))
        self.assertFalse(learning_pr.auto_merge_eligible(""))

    def test_a_fixture_is_a_smoke_replay_or_test_file(self):
        for ok in ("agents/replay/cases.json", "orchestrator/build_run_test.py", "templates/starter/backend/src/app.test.ts"):
            self.assertTrue(learning_pr.lesson_has_fixture([ok]), ok)
        self.assertTrue(learning_pr.lesson_has_fixture(["agents/smoke/fixtures/x.diff", "agents/smoke/expected.json"]))
        self.assertFalse(learning_pr.lesson_has_fixture(["agents/prompts/coder.md", "templates/starter/AGENTS.md"]))

    def test_a_smoke_fixture_must_be_a_diff_with_an_expected_entry(self):
        stray = ["agents/smoke/fixtures/missing-feature-flag.expected.json", "agents/smoke/fixtures/missing-feature-flag.intake.md"]
        self.assertFalse(learning_pr.lesson_has_fixture(stray))
        self.assertFalse(learning_pr.lesson_has_fixture(["agents/smoke/fixtures/x.diff"]))
        self.assertFalse(learning_pr.lesson_has_fixture(["agents/smoke/expected.json"]))


class Guardrails(unittest.TestCase):
    ADDED = ("diff --git a/agents/prompts/tester.md b/agents/prompts/tester.md\n--- a/agents/prompts/tester.md\n"
             "+++ b/agents/prompts/tester.md\n@@ -1,2 +1,3 @@\n context line\n+{line}\n context line\n")

    def test_shouting_in_added_prompt_lines_is_caught_wherever_it_appears(self):
        for line in ("**CRITICAL**: You MUST write your test results to the file", "**ACTION REQUIRED**: Before finishing, execute this",
                     "\u26a0\ufe0f CRITICAL: Every new user-facing endpoint", "WARNING: Previous tester runs have failed", "You MUST do it",
                     "This is IMPORTANT"):
            self.assertTrue(learning_pr.adds_emphasis(self.ADDED.format(line=line)), line)

    def test_plain_instructions_and_pre_existing_emphasis_are_fine(self):
        self.assertFalse(learning_pr.adds_emphasis(self.ADDED.format(line="Build the report with json.dump, not by hand.")))
        removed = "--- a/p.md\n+++ b/p.md\n-You MUST do it\n+You do it\n"
        self.assertFalse(learning_pr.adds_emphasis(removed))
        self.assertFalse(learning_pr.adds_emphasis("+++ b/p.md\n context MUST stay\n"))

    def test_a_smoke_fixture_must_be_a_diff_of_app_code(self):
        good = "diff --git a/backend/src/routes/x.ts b/backend/src/routes/x.ts\n+code\n"
        factory_diff = "diff --git a/agents/prompts/tester.md b/agents/prompts/tester.md\n+WARNING: x\n"
        self.assertIsNone(learning_pr.bad_fixture_reason({"agents/smoke/fixtures/a.diff": good}))
        self.assertIsNone(learning_pr.bad_fixture_reason({}))
        reason = learning_pr.bad_fixture_reason({"agents/smoke/fixtures/a.diff": good, "agents/smoke/fixtures/tester-no-output.diff": factory_diff})
        self.assertIn("tester-no-output.diff is not a diff of Managed App code", reason)
        self.assertIn("frontend/", learning_pr.bad_fixture_reason({"agents/smoke/fixtures/f.diff": "diff --git a/frontend/x b/frontend/x\n"}) or "frontend/")

    def test_existing_smoke_fixtures_all_pass_the_fixture_rule(self):
        root = Path(config.FACTORY_DIR) / "agents/smoke/fixtures"
        texts = {str(p): p.read_text() for p in root.glob("*.diff")}
        self.assertTrue(texts)
        self.assertIsNone(learning_pr.bad_fixture_reason(texts))


if __name__ == "__main__":
    unittest.main()
