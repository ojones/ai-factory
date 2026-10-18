# Tests for the Fly orphan audit. Run: python3 -m unittest discover -p "*_test.py" orchestrator
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fly_audit as f  # noqa: E402


class Orphans(unittest.TestCase):
    apps = [{"name": "ojones-todo", "machines": 1}, {"name": "ai-factory-growthbook", "machines": 1},
            {"name": "stray", "machines": 2}, {"name": "metrics", "machines": 1}]

    def test_only_apps_without_a_managed_repo_or_infra_role_are_orphans(self):
        found = f.orphans(self.apps, ["metrics"], lambda n: n == "ojones-todo")
        self.assertEqual([a["name"] for a in found], ["stray"])

    def test_nothing_is_reported_when_every_app_is_owned(self):
        self.assertEqual(f.orphans(self.apps[:2], [], lambda n: True), [])
        self.assertIn("No Fly app", f.render([], "personal"))

    def test_the_report_lists_each_orphan_and_deletes_nothing(self):
        text = f.render(f.orphans(self.apps, [], lambda n: False), "personal")
        self.assertIn("`stray`", text)
        self.assertNotIn("`ai-factory-growthbook`", text)
        self.assertIn("never deletes", text)


class Ledger(unittest.TestCase):
    def test_the_post_mortem_agents_spend_counts_toward_the_daily_cap(self):
        import build_run as b
        line_run = b.ledger_line("2026-10-13", "app", 1.5, "99")
        line_pm = b.ledger_line("2026-10-13", "retrospective", 0.25, "99-pm")
        self.assertEqual(b.ledger_total([line_run, line_pm], "2026-10-13"), 1.75)

    def test_record_agent_spend_writes_one_ledger_line_and_never_raises(self):
        from unittest import mock

        import build_run as b
        import retrospective as pm
        budget = mock.Mock()
        budget.refresh.return_value = 0.21
        with mock.patch.object(b, "record_spend_in_ledger") as rec:
            pm.record_agent_spend(budget, "jwt", "o/r", "tok", "7")
        rec.assert_called_once_with({"app": "retrospective", "spent_usd": 0.21}, "o/r", "7-pm", "tok")
        budget.refresh.side_effect = RuntimeError("down")
        pm.record_agent_spend(budget, "jwt", "o/r", "tok", "7")


class FlagSet(unittest.TestCase):
    def test_only_valid_names_make_a_key(self):
        import flag_set
        self.assertEqual(flag_set.feature_key("ojones-todo", "fast-heartbeat"), "ojones-todo.feature.fast-heartbeat")
        for app, slug in (("../x", "a"), ("a", "A b"), ("", "a"), ("a", "")):
            self.assertIsNone(flag_set.feature_key(app, slug))
        self.assertEqual(flag_set.main(["x", "app", "flag", "maybe"]), 2)


class Idle(unittest.TestCase):
    def test_days_idle_and_the_longest_idle_come_first(self):
        self.assertEqual(f.idle_days("2026-10-01T00:00:00Z", now=__import__("calendar").timegm((2026, 10, 11, 0, 0, 0))), 10)
        self.assertIsNone(f.idle_days("garbage"))
        text = f.idle_report([("new", 1), ("old", 90), ("unknown", None)])
        self.assertLess(text.index("`old`"), text.index("`new`"))
        self.assertIn("Nothing is retired automatically", text)


if __name__ == "__main__":
    unittest.main()
