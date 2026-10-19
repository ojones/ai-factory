import unittest

from flag_lifecycle import flag_manifest


class Manifest(unittest.TestCase):
    def test_new_slugs_only(self):
        base = '[{"slug":"a","description":"."}]'
        head = '[{"slug":"a","description":"."},{"slug":"b","description":"."}]'
        self.assertEqual(flag_manifest.new_flag_slugs(base, head), ["b"])

    def test_missing_base_or_garbage(self):
        self.assertEqual(flag_manifest.new_flag_slugs("", '[{"slug":"a"}]'), ["a"])
        self.assertEqual(flag_manifest.new_flag_slugs("[]", "not json"), [])

    def test_slug_pattern(self):
        for ok in ("todos-crud", "a1"):
            self.assertTrue(flag_manifest.SLUG_RE.fullmatch(ok))
        for bad in ("../x", "A", "a b", "", "-a", "a/b"):
            self.assertFalse(flag_manifest.SLUG_RE.fullmatch(bad))

    def test_the_github_key_of_a_flag_is_app_scoped_and_only_valid_names_make_one(self):
        self.assertEqual(flag_manifest.feature_key("ojones-todo", "fast-heartbeat"), "ojones-todo.feature.fast-heartbeat")
        for app, slug in (("../x", "a"), ("a", "A b"), ("", "a"), ("a", "")):
            self.assertIsNone(flag_manifest.feature_key(app, slug))

    def test_the_slugs_a_run_removed_are_the_flags_it_retired(self):
        base = '[{"slug":"a"},{"slug":"b"}]'
        self.assertEqual(flag_manifest.removed_flag_slugs(base, '[{"slug":"b"}]'), ["a"])
        self.assertEqual(flag_manifest.removed_flag_slugs(base, base), [])
        self.assertEqual(flag_manifest.removed_flag_slugs("not json", base), [])


if __name__ == "__main__":
    unittest.main()
