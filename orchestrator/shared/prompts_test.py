import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config, prompts  # noqa: E402


class Prompts(unittest.TestCase):
    # Every role prompt's placeholders are exactly the ones the orchestrator supplies.
    SUPPLIED = {
        "coder": {"app_name", "round", "task", "findings_path", "issue_ref"},
        "reviewer": {"app_name", "base_sha", "head_sha", "verdict_path", "rubric", "spec"},
        "reviewer-fast": {"app_name", "base_sha", "head_sha", "rubric"},
        "tester": {"app_name", "app_url", "head_sha", "report_path", "previous_report", "spec", "api_check", "ui_section", "new_flags"},
        "planner": {"app_name", "build_kind", "task", "plan_path", "spec"},
        "pipeline": {"app_name", "head_sha", "failure_run_url", "diagnosis_path", "context_dir"},
        "retrospective": {"facts_path", "result_path", "categories"},
    }

    def test_placeholders(self):
        import re
        for role, supplied in self.SUPPLIED.items():
            text = (config.FACTORY_DIR / "agents" / "prompts" / f"{role}.md").read_text()
            self.assertEqual(set(re.findall(r"\{\{(\w+)\}\}", text)) - supplied, set(), role)

    def test_render_replaces_and_rejects_leftovers(self):
        self.assertEqual(prompts.render("hi {{a}} {{a}}", {"a": 1}), "hi 1 1")
        with self.assertRaises(ValueError):
            prompts.render("hi {{a}} {{b}}", {"a": 1})


if __name__ == "__main__":
    unittest.main()
