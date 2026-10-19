import unittest

from flag_lifecycle import dark_feature, retirement_check


class DarkFeatureRemoval(unittest.TestCase):
    LABELS = ["update-app-intake", "app:notes", "flag:pin-notes", "dark-broken", "needs-human"]

    def test_a_person_can_approve_only_a_story_whose_retries_are_used_up(self):
        self.assertEqual(dark_feature.dark_removal_target(self.LABELS), ("notes", "pin-notes", None))
        for missing, why in (("dark-broken", "no broken dark feature"), ("needs-human", "retries are not used up"),
                             ("flag:pin-notes", "exactly one flag"), ("app:notes", "exactly one flag"), ("update-app-intake", "not an Update App Intake")):
            app, slug, reason = dark_feature.dark_removal_target([l for l in self.LABELS if l != missing])
            self.assertIsNone(app)
            self.assertIn(why, reason, missing)

    def test_more_than_one_flag_or_app_is_refused_rather_than_guessed(self):
        self.assertIsNotNone(dark_feature.dark_removal_target(self.LABELS + ["flag:other"])[2])
        self.assertIsNotNone(dark_feature.dark_removal_target(self.LABELS + ["app:other"])[2])

    def test_the_removal_task_deletes_the_feature_and_adds_nothing(self):
        task = dark_feature.dark_removal_task("pin-notes", 12)
        self.assertIn("#12", task)
        self.assertIn("`flags.json`", task)
        self.assertIn("never released", task)
        self.assertEqual(retirement_check.retire_slugs(task), [])  # not the keep-it-on retirement of a released flag


if __name__ == "__main__":
    unittest.main()
