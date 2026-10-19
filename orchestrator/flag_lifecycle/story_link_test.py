import unittest

from flag_lifecycle import story_link


class StoryAndFlagReferenceEachOther(unittest.TestCase):
    def test_the_title_carries_the_flag_and_a_retry_does_not_pile_up_tags(self):
        self.assertEqual(story_link.title_with_flags("app: add a page", ["todo-ui"]), "app: add a page [flag: todo-ui]")
        self.assertEqual(story_link.title_with_flags("app: add a page [flag: todo-ui]", ["todo-ui"]), "app: add a page [flag: todo-ui]")
        self.assertEqual(story_link.title_with_flags("app: a [flag: x]", ["y", "z"]), "app: a [flags: y, z]")
        self.assertEqual(story_link.title_with_flags("app: a", []), "app: a")

    def test_labels_descriptions_and_tags(self):
        self.assertEqual(story_link.flag_label("todo-ui"), "flag:todo-ui")
        self.assertIsNone(story_link.flag_label("x" * 60))
        text = story_link.flag_description("https://github.com/o/r/issues/94", "app: a page [flag: todo-ui]")
        self.assertTrue(text.startswith("https://github.com/o/r/issues/94 "))
        self.assertNotIn("[flag", text)
        self.assertEqual(story_link.flag_tags("94", "app"), ["intake-94", "app-app"])


if __name__ == "__main__":
    unittest.main()


class Linking(unittest.TestCase):
    def link(self, title="app: add a page", slugs=("todo-ui",)):
        calls, labels = [], []
        new_title = story_link.link(lambda args, token=None, check=True: calls.append(args), lambda *a: labels.append(a[1]), "o/f", "tok", "94", title, "app",
                                    "77", "https://run", list(slugs))
        return new_title, calls, labels

    def test_the_story_gets_the_label_the_title_tag_and_a_comment_with_the_full_key(self):
        title, calls, labels = self.link()
        self.assertEqual((title, labels), ("app: add a page [flag: todo-ui]", ["flag:todo-ui"]))
        self.assertIn(["issue", "edit", "94", "--repo", "o/f", "--add-label", "flag:todo-ui"], calls)
        self.assertIn(["issue", "edit", "94", "--repo", "o/f", "--title", "app: add a page [flag: todo-ui]"], calls)
        comment = next(c for c in calls if c[1] == "comment")
        self.assertIn("`app.feature.todo-ui`", comment[comment.index("--body") + 1])

    def test_a_title_that_already_has_the_tag_is_not_edited_again(self):
        title, calls, _ = self.link(title="app: add a page [flag: todo-ui]")
        self.assertEqual(title, "app: add a page [flag: todo-ui]")
        self.assertFalse(any("--title" in c for c in calls))

    def test_a_slug_too_long_for_a_label_gets_no_label(self):
        _, _, labels = self.link(slugs=("x" * 60,))
        self.assertEqual(labels, [])
