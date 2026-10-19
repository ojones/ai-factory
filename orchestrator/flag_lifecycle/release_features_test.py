import unittest

from shared.run_stops import NeedsHuman

from flag_lifecycle import release_features
from flag_lifecycle.fake_growthbook import FakeGrowthBook


def off():
    return {"environments": {"production": {"enabled": False, "rules": []}}}


def on():
    return {"environments": {"production": {"enabled": True, "rules": []}}}


def check(gb, flags, own=()):
    return release_features.check_flags(gb, "app", flags, list(own))


class CheckFlags(unittest.TestCase):
    def test_the_storys_own_flag_that_is_off_is_to_be_switched_on(self):
        gb = FakeGrowthBook({"app.feature.issue-9": off()})
        self.assertEqual(check(gb, ["issue-9"], own=["issue-9"]), (["app.feature.issue-9"], [], []))

    def test_any_other_existing_flag_is_left_exactly_as_it_is(self):
        gb = FakeGrowthBook({"app.feature.old": off()})
        self.assertEqual(check(gb, ["old"], own=["issue-9"]), ([], ["app.feature.old"], []))

    def test_the_storys_own_flag_that_is_already_on_is_not_touched(self):
        gb = FakeGrowthBook({"app.feature.issue-9": on()})
        self.assertEqual(check(gb, ["issue-9"], own=["issue-9"]), ([], ["app.feature.issue-9"], []))

    def test_a_flag_that_does_not_exist_is_reported_and_never_created(self):
        gb = FakeGrowthBook()
        self.assertEqual(check(gb, ["ghost"], own=["ghost"]), ([], [], ["ghost"]))
        self.assertEqual([c[0] for c in gb.calls], ["GET"])

    def test_checking_changes_nothing_so_a_missing_flag_leaves_the_others_untouched(self):
        gb = FakeGrowthBook({"app.feature.issue-9": off()})
        check(gb, ["issue-9", "ghost"], own=["issue-9"])
        self.assertFalse(gb.production_enabled("app.feature.issue-9"))

    def test_a_slug_that_is_not_valid_stops_before_anything_is_looked_up(self):
        gb = FakeGrowthBook()
        with self.assertRaises(NeedsHuman):
            check(gb, ["good", "../Not Valid"])
        self.assertEqual(gb.calls, [])


class SwitchOn(unittest.TestCase):
    def test_each_key_is_switched_on_in_production_with_no_rules(self):
        gb = FakeGrowthBook({"app.feature.a": off(), "app.feature.b": off()})
        release_features.switch_on(gb, ["app.feature.a"])
        self.assertTrue(gb.production_enabled("app.feature.a"))
        self.assertFalse(gb.production_enabled("app.feature.b"))

    def test_nothing_to_switch_makes_no_call(self):
        gb = FakeGrowthBook()
        release_features.switch_on(gb, [])
        self.assertEqual(gb.calls, [])


if __name__ == "__main__":
    unittest.main()
