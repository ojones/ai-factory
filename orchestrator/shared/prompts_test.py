import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config  # noqa: E402


class Prompts(unittest.TestCase):
    # Every role prompt's placeholders are exactly the ones the orchestrator supplies.
    SUPPLIED = {
        "coder": {"app_name", "round", "task", "findings_path", "build_kind", "issue_ref"},
        "reviewer": {"app_name", "base_sha", "head_sha", "verdict_path", "rubric", "build_kind", "spec"},
        "reviewer-fast": {"app_name", "base_sha", "head_sha", "rubric", "build_kind"},
        "tester": {"app_name", "app_url", "head_sha", "report_path", "previous_report", "build_kind", "spec", "api_check", "ui_section", "new_flags"},
        "planner": {"app_name", "build_kind", "task", "plan_path", "spec"},
        "pipeline": {"app_name", "head_sha", "failure_run_url", "diagnosis_path", "context_dir"},
        "retrospective": {"facts_path", "result_path", "categories"},
    }

    def test_placeholders(self):
        import re
        for role, supplied in self.SUPPLIED.items():
            text = (config.FACTORY_DIR / "agents" / "prompts" / f"{role}.md").read_text()
            self.assertEqual(set(re.findall(r"\{\{(\w+)\}\}", text)) - supplied, set(), role)


if __name__ == "__main__":
    unittest.main()
