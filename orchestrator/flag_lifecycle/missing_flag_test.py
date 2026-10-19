import unittest

from flag_lifecycle import missing_flag


class Classifying(unittest.TestCase):
    def test_a_missing_flag_the_code_reads_is_dark_and_one_it_does_not_is_live(self):
        reads = {"read-it": True, "ignored": False}
        self.assertEqual(missing_flag.split(["read-it", "ignored"], lambda s: reads[s]), (["read-it"], ["ignored"]))
        self.assertEqual(missing_flag.split([], lambda s: True), ([], []))


class Guesses(unittest.TestCase):
    def test_no_flag_to_name_means_the_coder_chose_its_own(self):
        self.assertIn("chose `x` itself", missing_flag.guess("x", None))

    def test_a_second_flag_besides_the_one_the_orchestrator_created(self):
        self.assertIn("besides the flag the Orchestrator created", missing_flag.guess("extra", "issue-9"))

    def test_the_named_flag_itself_missing_means_it_was_removed_from_growthbook(self):
        self.assertIn("gone from GrowthBook", missing_flag.guess("issue-9", "issue-9"))

    def test_a_note_carries_the_slug_the_kind_and_the_guess(self):
        note = missing_flag.note("x", "missing_dark", None)
        self.assertEqual((note["slug"], note["kind"]), ("x", "missing_dark"))
        self.assertTrue(note["guess"])


class Messages(unittest.TestCase):
    def test_a_dark_flag_says_nothing_was_rolled_back_and_what_to_add(self):
        text = missing_flag.dark_message(["x"], None)
        self.assertIn("deployed dark", text)
        self.assertIn("Nothing was rolled back", text)
        self.assertIn("A flag that can be turned on has to exist", text)

    def test_a_live_change_with_clean_tests_is_left_alone_and_one_with_a_failure_is_rolled_back(self):
        self.assertIn("left as it is", missing_flag.live_message(["x"], None, False))
        self.assertIn("rolled back", missing_flag.live_message(["x"], None, True))


if __name__ == "__main__":
    unittest.main()
