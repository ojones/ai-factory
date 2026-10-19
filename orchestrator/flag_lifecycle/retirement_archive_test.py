import unittest

from flag_lifecycle import retirement_archive
from flag_lifecycle.fake_growthbook import FakeGrowthBook


def on():
    return {"environments": {"production": {"enabled": True, "rules": []}}}


class Archive(unittest.TestCase):
    def test_only_the_flags_a_run_removed_from_the_manifest_are_archived(self):
        gb = FakeGrowthBook({"app.feature.a": on(), "app.feature.b": on()})
        done = retirement_archive.archive_removed(gb, "app", '[{"slug":"a"},{"slug":"b"}]', '[{"slug":"b"}]')
        self.assertEqual(done, [("a", 200)])
        self.assertTrue(gb.features["app.feature.a"]["archived"])
        self.assertNotIn("archived", gb.features["app.feature.b"])

    def test_nothing_removed_means_no_call(self):
        gb = FakeGrowthBook()
        self.assertEqual(retirement_archive.archive_removed(gb, "app", "[]", "[]"), [])
        self.assertEqual(gb.calls, [])


if __name__ == "__main__":
    unittest.main()
