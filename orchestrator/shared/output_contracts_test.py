import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config  # noqa: E402

CONTRACTS = {
    "reviewer": ("analysis", "findings", "verdict", "blocking", "minor"),
    "tester": ("passed", "results", "limitations", "blocked", "not_run"),
    "planner": ("requirements", "assumptions", "open_questions", "change_sets"),
    "pipeline": ("category", "summary", "fix_request", "retry_recommended"),
}


class OutputContracts(unittest.TestCase):
    def test_each_prompt_names_every_key_the_orchestrator_reads(self):
        for role, keys in CONTRACTS.items():
            text = (config.FACTORY_DIR / "agents" / "prompts" / f"{role}.md").read_text()
            missing = [key for key in keys if key not in text]
            self.assertEqual(missing, [], f"{role} prompt does not name {missing}")


if __name__ == "__main__":
    unittest.main()
