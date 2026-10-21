import unittest

from monitoring import fly_audit as f


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


class Idle(unittest.TestCase):
    def test_days_idle_and_the_longest_idle_come_first(self):
        self.assertEqual(f.idle_days("2026-10-01T00:00:00Z", now=__import__("calendar").timegm((2026, 10, 11, 0, 0, 0))), 10)
        self.assertIsNone(f.idle_days("garbage"))
        text = f.idle_report([("new", 1), ("old", 90), ("unknown", None)])
        self.assertLess(text.index("`old`"), text.index("`new`"))
        self.assertIn("Nothing is retired automatically", text)


if __name__ == "__main__":
    unittest.main()
