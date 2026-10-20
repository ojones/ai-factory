import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import spend_ledger  # noqa: E402


class RunSpendLedger(unittest.TestCase):
    def test_the_post_mortem_agents_spend_counts_toward_the_daily_cap(self):
        line_run = spend_ledger.ledger_line("2026-10-13", "app", 1.5, "99")
        line_pm = spend_ledger.ledger_line("2026-10-13", "retrospective", 0.25, "99-pm")
        self.assertEqual(spend_ledger.ledger_total([line_run, line_pm], "2026-10-13"), 1.75)

    def test_record_agent_spend_writes_one_ledger_line_and_never_raises(self):

        from retrospective import agent_run
        budget = mock.Mock()
        budget.refresh.return_value = 0.21
        with mock.patch.object(agent_run.spend_ledger, "record_spend_in_ledger") as rec:
            agent_run.record_agent_spend(budget, "jwt", "o/r", "tok", "7")
        rec.assert_called_once_with({"app": "retrospective", "spent_usd": 0.21}, "o/r", "7-pm", "tok")
        budget.refresh.side_effect = RuntimeError("down")
        agent_run.record_agent_spend(budget, "jwt", "o/r", "tok", "7")


if __name__ == "__main__":
    unittest.main()
