import json
import unittest

from flag_lifecycle import dark_feature, flag_slug, release_features, retirement_archive, retirement_check, retirement_selection, watchdog
from flag_lifecycle.fake_growthbook import FakeGrowthBook

APP, KEY = "app", "app.feature.pin-notes"


def state_entry(slug, run, date, state="released"):
    return {"key": f"{APP}.feature.{slug}", "date": date, "run_url": f"https://github.com/o/r/actions/runs/{run}", "state": state}


class OneFlagThroughItsLife(unittest.TestCase):
    def start(self, gb, slug="pin-notes"):
        flag_slug.ensure_feature(gb, APP, slug, "https://github.com/o/f/issues/9", "app: pin notes", "9")

    def release(self, gb, flags, own=("pin-notes",)):
        to_switch, kept, missing = release_features.check_flags(gb, APP, flags, list(own))
        release_features.switch_on(gb, to_switch)
        return to_switch, kept, missing

    def test_5_1_to_5_4_dark_then_released_then_eligible_then_retired(self):
        gb = FakeGrowthBook()
        self.start(gb)
        self.assertFalse(gb.production_enabled(KEY), msg="5.1: dark: the code is deployed, the flag exists and is off")
        released, _, _ = self.release(gb, ["pin-notes"])
        self.assertEqual(released, [KEY])
        self.assertTrue(gb.production_enabled(KEY))
        state = [state_entry("pin-notes", 100, "2026-10-10"), state_entry("later", 200, "2026-10-11")]
        self.assertEqual(retirement_selection.piggyback_slugs(state, {"pin-notes", "later"}, 5), ["pin-notes"], msg="5.3")
        self.assertEqual(retirement_selection.piggyback_slugs(state[:1], {"pin-notes"}, 5), [], msg="the newest release keeps its flag")
        task = "Add a thing" + retirement_selection.retirement_block(["pin-notes"])
        self.assertEqual(retirement_check.retire_slugs(task), ["pin-notes"])
        still_there = retirement_check.code_references(["abc:backend/src/a.ts:3:  isFeatureEnabled(res, \"pin-notes\")"])
        self.assertIsNotNone(retirement_check.retirement_problem("pin-notes", still_there))
        self.assertIsNone(retirement_check.retirement_problem("pin-notes", []))
        done = retirement_archive.archive_removed(gb, APP, json.dumps([{"slug": "pin-notes"}]), "[]")
        self.assertEqual(done, [("pin-notes", 200)])
        self.assertTrue(gb.features[KEY]["archived"])

    def test_5_2_to_5_5_to_5_2_the_watchdog_switches_it_off_and_the_fix_releases_the_same_flag(self):
        gb = FakeGrowthBook()
        self.start(gb)
        self.release(gb, ["pin-notes"])
        self.assertEqual(watchdog.disable_flags(gb, [KEY]), [], msg="5.5: off, the code stays in main")
        self.assertFalse(gb.production_enabled(KEY))
        released, kept, _ = self.release(gb, ["pin-notes"], own=())
        self.assertEqual((released, kept, gb.production_enabled(KEY)), ([], [KEY], False))
        released, _, _ = self.release(gb, ["pin-notes"])
        self.assertEqual((released, gb.production_enabled(KEY)), ([KEY], True))

    def test_a_flag_that_was_never_created_is_not_made_up_at_release(self):
        gb = FakeGrowthBook()
        self.assertEqual(self.release(gb, ["pin-notes"]), ([], [], ["pin-notes"]))
        self.assertNotIn(KEY, gb.features)

    def test_5_5_to_5_7_a_dark_feature_a_person_approves_is_removed_as_a_flagless_change(self):
        labels = ["update-app-intake", "app:app", "flag:pin-notes", "dark-broken", "needs-human"]
        app, slug, why = dark_feature.dark_removal_target(labels)
        self.assertEqual((app, slug, why), ("app", "pin-notes", None))
        task = dark_feature.dark_removal_task(slug, 9)
        self.assertIn("flags.json", task)
        self.assertEqual(retirement_check.retire_slugs(task), [])
        self.assertTrue(dark_feature.is_dark_broken({"flags": ["pin-notes"], "commits": ["h"], "outcome": "round_limit"}))
        self.assertFalse(dark_feature.is_dark_broken({"flags": ["pin-notes"], "commits": ["h"], "outcome": "released"}))


if __name__ == "__main__":
    unittest.main()
