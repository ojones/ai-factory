import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bugs import route_bug  # noqa: E402

STATE = {"flags": [{"key": "demo.feature.issue-12", "state": "released"},
                   {"key": "demo.feature.issue-20", "state": "switched off by the watchdog"},
                   {"key": "demo.feature.issue-30", "state": "dark (failed its checks; fixed forward by a fix child)"},
                   {"key": "demo.feature.other", "state": "released"}]}


class FlagStates(unittest.TestCase):
    # STEP 8.1, 8.2: the flag's state in the App State decides whether a story is released or dark (INV-60).
    def test_only_a_flag_released_and_still_on_is_released_and_every_other_state_is_dark(self):
        self.assertEqual(route_bug.flag_states(STATE), {12: "released", 20: "dark", 30: "dark"})

    def test_a_flag_never_released_is_dark_whatever_words_its_state_uses(self):
        for state in ("dark", "off", "never released", "", None):
            self.assertEqual(route_bug.flag_states({"flags": [{"key": "demo.feature.issue-7", "state": state}]}), {7: "dark"})

    def test_only_issue_named_flags_are_stories_and_an_empty_or_unreadable_state_knows_none(self):
        for state in ({}, None, {"flags": None}, {"flags": [{"state": "released"}]}, {"flags": [{"key": "demo.feature.other", "state": "released"}]}):
            self.assertEqual(route_bug.flag_states(state), {})


class Attach(unittest.TestCase):
    # STEP 8.1, 8.4: a bug is tied to a story by the flag it names, never by a guess.
    states = {12: "released", 20: "dark"}

    def test_an_error_that_names_a_dark_flag_belongs_to_that_dark_story_whose_open_child_will_wait(self):
        self.assertEqual(route_bug.attach("TypeError evaluating demo.feature.issue-20", self.states), (20, "issue-20", False))

    def test_an_error_that_names_a_released_flag_is_a_regression_in_a_released_story(self):
        self.assertEqual(route_bug.attach("flag issue-12 on, then TypeError", self.states), (12, "issue-12", True))

    def test_the_first_flag_the_app_state_knows_wins_and_an_unknown_one_before_it_is_skipped(self):
        self.assertEqual(route_bug.attach("issue-99 then issue-20 then issue-12", self.states), (20, "issue-20", False))

    def test_a_longer_number_is_not_mistaken_for_a_shorter_story(self):
        self.assertEqual(route_bug.attach("issue-120 failed", self.states), (None, None, None))

    def test_an_error_with_no_known_flag_is_tied_to_no_story_and_claims_nothing(self):
        for text in ("TypeError: x is undefined", "", None, "issue-99 is not in the app state"):
            self.assertEqual(route_bug.attach(text, self.states), (None, None, None))


if __name__ == "__main__":
    unittest.main()
