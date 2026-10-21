import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from factory_change import pause, plan  # noqa: E402

GOOD = "## Observable failure\nChild 3 is never filed.\n\n## Requirements\n1. Every change set is filed under the Intake\n\n## Reproduction\n{repro}\n"


def factory_with(test_body):
    root = Path(tempfile.mkdtemp())
    (root / "orchestrator").mkdir()
    (root / "orchestrator" / "case_test.py").write_text(f"import unittest\n\nclass Case(unittest.TestCase):\n    def test_it(self):\n        {test_body}\n", encoding="utf-8")
    return root


class Gate(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        self.number = self.gh.add(5)
        patcher = mock.patch.object(github, "run", self.gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def gate(self, repro, test_body="self.fail('x')"):
        self.gh.issues[self.number]["body"] = GOOD.format(repro=repro)
        return plan.gate("o/f", "t", self.number, factory_with(test_body), 6)

    def test_a_ticket_with_a_failing_reproduction_goes_on_to_the_planner(self):
        self.assertIsNone(self.gate("case_test.Case.test_it"))

    def test_a_ticket_with_no_reproduction_goes_on_for_the_coder_to_write_one(self):
        self.assertIsNone(self.gate("none"))

    def test_a_reproduction_that_passes_on_main_is_refused_before_any_agent(self):
        self.assertEqual(self.gate("case_test.Case.test_it", "pass"), "refused")
        self.assertIn("No Agent was run", self.gh.comments[self.number][0])

    def test_a_ticket_without_checkable_requirements_is_refused(self):
        self.gh.issues[self.number]["body"] = "just fix it"
        self.assertEqual(plan.gate("o/f", "t", self.number, factory_with("pass"), 6), "refused")

    def test_a_paused_process_plans_nothing(self):
        pause.pause("o/f", "t", "a regression")
        self.assertEqual(self.gate("none"), "paused")


if __name__ == "__main__":
    unittest.main()
