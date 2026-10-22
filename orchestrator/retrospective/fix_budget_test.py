import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrospective import fix_budget, tracker  # noqa: E402


class FixedToday(unittest.TestCase):
    def test_it_counts_todays_bug_tickets_for_the_app_in_the_factory_repo(self):
        calls = []

        def gh(args, token, check=False):
            calls.append(args)
            return mock.Mock(stdout=json.dumps([{"number": 1}, {"number": 2}]))
        with mock.patch.object(tracker, "gh", gh):
            n = fix_budget.warnings_fixed_today("o/ai-factory", "t", "demo", datetime(2026, 10, 19, 5, tzinfo=timezone.utc))
        self.assertEqual(n, 2)
        args = calls[0]
        self.assertEqual(args[args.index("--search") + 1], "created:>=2026-10-19")
        self.assertEqual([args[i + 1] for i, a in enumerate(args) if a == "--label"], ["bug", "app:demo"])

    def test_a_failed_listing_raises_so_the_caller_can_fail_closed(self):
        def gh(args, token, check=False):
            raise RuntimeError("gh issue list failed")
        with mock.patch.object(tracker, "gh", gh), self.assertRaises(RuntimeError):
            fix_budget.warnings_fixed_today("o/f", "t", "demo")

    def test_no_output_is_zero(self):
        with mock.patch.object(tracker, "gh", lambda *a, **k: mock.Mock(stdout="")):
            self.assertEqual(fix_budget.warnings_fixed_today("o/f", "t", "demo"), 0)


if __name__ == "__main__":
    unittest.main()
