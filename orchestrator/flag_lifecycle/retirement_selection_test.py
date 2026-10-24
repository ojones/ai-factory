import unittest

from flag_lifecycle import retirement_check, retirement_selection


def entry(slug, run, date="2026-10-10", state="released"):
    return {"key": f"app.feature.{slug}", "date": date, "run_url": f"https://github.com/o/r/actions/runs/{run}", "state": state}


class Candidates(unittest.TestCase):
    manifest = {"a", "b", "c"}

    def test_a_flag_is_retired_only_after_a_later_release(self):
        flags = [entry("a", 100), entry("b", 200)]
        self.assertEqual(retirement_selection.candidates(flags, self.manifest), [("a", 100)], msg="b is the newest release: keeps its flag")
        self.assertEqual(retirement_selection.candidates([entry("a", 100)], self.manifest), [], msg="nothing came after it")

    def test_a_flag_the_watchdog_switched_off_or_missing_from_the_manifest_is_never_retired(self):
        flags = [entry("a", 100, state="switched off by the watchdog"), entry("b", 200), entry("c", 300)]
        self.assertEqual(retirement_selection.candidates(flags, {"b", "c"}), [("b", 200)])
        self.assertEqual(retirement_selection.candidates(flags, {"c"}), [])

    def test_oldest_first_and_a_backlog_may_retire_several_up_to_the_limit(self):
        flags = [entry("c", 300), entry("a", 100), entry("b", 200), entry("d", 400)]
        manifest = {"a", "b", "c", "d"}
        self.assertEqual(retirement_selection.piggyback_slugs(flags, manifest, 5), ["a", "b", "c"], msg="d is the newest release")
        self.assertEqual(retirement_selection.piggyback_slugs(flags, manifest, 2), ["a", "b"])
        self.assertEqual(retirement_selection.piggyback_slugs(flags, manifest, 0), [])


class Stories(unittest.TestCase):
    def test_issue_of_reads_the_story_each_flag_came_from(self):
        flags = [{**entry("a", 1), "issue": 94}, entry("b", 2), {**entry("c", 3), "issue": "x"}]
        self.assertEqual(retirement_selection.issue_of(flags), {"a": 94})


class Texts(unittest.TestCase):
    def test_the_task_block_and_the_spec_note_carry_one_retire_line_per_flag(self):
        self.assertEqual(retirement_selection.retirement_block([]), "")
        self.assertEqual(retirement_selection.retirement_note([]), "")
        block, note = retirement_selection.retirement_block(["a", "b"]), retirement_selection.retirement_note(["a", "b"])
        for text in (block, note):
            self.assertEqual(retirement_check.retire_slugs(text), ["a", "b"])
        self.assertIn("its own commit", block)
        self.assertIn("ordinary visitor", note)

    def test_retire_slugs_reads_every_line_once(self):
        self.assertEqual(retirement_check.retire_slugs("x\nretire-flag: a\nretire-flag: b-c\nretire-flag: a\n"), ["a", "b-c"])
        self.assertEqual(retirement_check.retire_slugs("Add a button"), [])


if __name__ == "__main__":
    unittest.main()
