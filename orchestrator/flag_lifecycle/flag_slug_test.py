import json
import unittest

from shared.run_stops import NeedsHuman

from flag_lifecycle import flag_slug
from flag_lifecycle.fake_growthbook import FakeGrowthBook

URL, TITLE = "https://github.com/o/f/issues/12", "app: add a page"


class Naming(unittest.TestCase):
    def test_a_flag_is_named_after_its_issue(self):
        self.assertEqual(flag_slug.for_story(12), "issue-12")
        self.assertEqual(flag_slug.for_story("7"), "issue-7")

    def test_the_placeholder_in_a_task_becomes_the_slug(self):
        self.assertEqual(flag_slug.name_in(f"use `{flag_slug.SLOT}` here and {flag_slug.SLOT}", "issue-12"), "use `issue-12` here and issue-12")
        self.assertEqual(flag_slug.name_in("no placeholder", "issue-12"), "no placeholder")
        self.assertEqual(flag_slug.name_in(None, "issue-12"), "")


class EnsureFeature(unittest.TestCase):
    def test_a_missing_feature_is_created_off_with_the_story_pointer(self):
        gb = FakeGrowthBook()
        self.assertTrue(flag_slug.ensure_feature(gb, "app", "issue-12", URL, TITLE, "12"))
        feature = gb.features["app.feature.issue-12"]
        self.assertFalse(gb.production_enabled("app.feature.issue-12"))
        self.assertTrue(feature["description"].startswith(URL))
        self.assertEqual(feature["tags"], ["intake-12", "app-app"])

    def test_it_is_created_once_and_an_existing_feature_is_never_touched(self):
        on = {"environments": {"production": {"enabled": True, "rules": [{"x": 1}]}}}
        gb = FakeGrowthBook({"app.feature.issue-12": on})
        self.assertFalse(flag_slug.ensure_feature(gb, "app", "issue-12", URL, TITLE, "12"))
        self.assertEqual([c[0] for c in gb.calls], ["GET"])
        self.assertTrue(gb.production_enabled("app.feature.issue-12"))
        second = FakeGrowthBook()
        flag_slug.ensure_feature(second, "app", "issue-12", URL, TITLE, "12")
        self.assertFalse(flag_slug.ensure_feature(second, "app", "issue-12", URL, TITLE, "12"))

    def test_it_is_still_created_without_the_pointer_if_growthbook_refuses_the_extras(self):
        gb = FakeGrowthBook()
        gb.refuse_extras = True
        self.assertTrue(flag_slug.ensure_feature(gb, "app", "issue-12", URL, TITLE, "12"))
        self.assertIsNone(gb.features["app.feature.issue-12"]["description"])

    def test_growthbook_being_down_stops_the_run_before_any_code_is_written(self):
        def down(method, path, body=None):
            return 500, {}
        with self.assertRaises(NeedsHuman):
            flag_slug.ensure_feature(down, "app", "issue-12", URL, TITLE, "12")


class Manifest(unittest.TestCase):
    def test_the_flag_is_recorded_with_the_issue_reference_first_and_only_once(self):
        text = flag_slug.add_to_manifest('[{"slug": "old", "description": "o/f#1: x"}]', "issue-12", "o/f#12", "add a\npage")
        flags = json.loads(text)
        self.assertEqual([f["slug"] for f in flags], ["old", "issue-12"])
        self.assertEqual(flags[1]["description"], "o/f#12: add a page")
        self.assertEqual(flag_slug.add_to_manifest(text, "issue-12", "o/f#12", "again"), text)

    def test_an_empty_or_missing_manifest_starts_a_list_and_garbage_stops_the_run(self):
        self.assertEqual(json.loads(flag_slug.add_to_manifest("", "issue-1", "o/f#1", "x"))[0]["slug"], "issue-1")
        with self.assertRaises(NeedsHuman):
            flag_slug.add_to_manifest("not json", "issue-1", "o/f#1", "x")


if __name__ == "__main__":
    unittest.main()
