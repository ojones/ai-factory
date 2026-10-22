import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import run_stops, spend_ledger  # noqa: E402

from build_run import track_progress  # noqa: E402
from build_run.run import BuildRun  # noqa: E402


class SpendLedger(unittest.TestCase):
    def test_line_round_trips_and_only_todays_lines_count(self):
        line = spend_ledger.ledger_line("2026-10-10", "notes", 0.5, "42")
        self.assertEqual(line, "ledger 2026-10-10 notes 0.5000 run:42")
        comments = [line, spend_ledger.ledger_line("2026-10-10", "todo", 1.25, "43"), spend_ledger.ledger_line("2026-10-09", "todo", 9.0, "40"),
                    "a human comment", "ledger 2026-10-10 notes lots run:44", ""]
        self.assertEqual(spend_ledger.ledger_total(comments, "2026-10-10"), 1.75)

    def test_a_run_id_seen_twice_counts_once(self):
        line = spend_ledger.ledger_line("2026-10-10", "notes", 0.5, "42")
        self.assertEqual(spend_ledger.ledger_total([line, line], "2026-10-10"), 0.5)

    def make(self, cap, comments, issue=7, code=0):
        run = object.__new__(BuildRun)
        run.lim, run.factory_repo, run.factory_token = {"daily_cost_cap_usd": cap}, "o/f", "t"
        run.state = track_progress.State("/tmp/unused-state.json", "x", "1", "u")
        listing = json.dumps([{"number": issue}] if issue else [])
        run.gh = mock.Mock(side_effect=[mock.Mock(returncode=code, stdout=listing), mock.Mock(returncode=code, stdout="\n".join(comments))])
        return run

    def today_line(self, usd, run_id):
        return spend_ledger.ledger_line(time.strftime("%Y-%m-%d", time.gmtime()), "a", usd, run_id)

    def test_the_cap_stops_a_new_run_and_records_what_was_spent(self):
        run = self.make(5.0, [self.today_line(3.0, "1"), self.today_line(2.5, "2")])
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.check_daily_cap()
        self.assertIn("$5.50", str(cm.exception))
        self.assertEqual(run.state.d["daily_spent_usd"], 5.5)

    def test_under_the_cap_zero_cap_and_no_ledger_yet_all_let_it_run(self):
        self.make(5.0, [self.today_line(3.0, "1")]).check_daily_cap()
        run = self.make(0, [self.today_line(99.0, "1")])
        run.check_daily_cap()
        run.gh.assert_not_called()
        self.make(5.0, [], issue=None).check_daily_cap()

    def test_a_ledger_that_cannot_be_read_stops_the_run(self):
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            self.make(5.0, [], code=1).check_daily_cap()
        self.assertIn("cannot be checked", str(cm.exception))


class RecordSpend(unittest.TestCase):
    def test_a_failed_write_prints_the_line_to_add_by_hand(self):
        with mock.patch.object(spend_ledger, "post_ledger_line", side_effect=RuntimeError("boom")), mock.patch("builtins.print") as shown:
            spend_ledger.record_spend_in_ledger({"app": "a", "spent_usd": 1.5}, "o/f", "42", "t")
        self.assertIn("run:42", shown.call_args.args[0])
        self.assertIn("::warning::", shown.call_args.args[0])

    def test_nothing_spent_writes_nothing(self):
        with mock.patch.object(spend_ledger, "post_ledger_line") as post:
            spend_ledger.record_spend_in_ledger({"app": "a", "spent_usd": 0}, "o/f", "42", "t")
        post.assert_not_called()

    def test_todays_spend_fails_closed_and_treats_no_ledger_as_none(self):
        with self.assertRaises(run_stops.NeedsHuman):
            spend_ledger.todays_spend(lambda *a: mock.Mock(returncode=1, stdout=""), "o/f", "t")
        self.assertIsNone(spend_ledger.todays_spend(lambda *a: mock.Mock(returncode=0, stdout="[]"), "o/f", "t"))


if __name__ == "__main__":
    unittest.main()
