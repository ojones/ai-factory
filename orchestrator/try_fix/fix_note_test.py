import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import fix_note  # noqa: E402


class FixNote(unittest.TestCase):
    def test_the_note_names_the_failed_child_and_asks_for_the_broken_behaviour_to_be_tested(self):
        note = fix_note.fix_note(20)
        self.assertIn("#20", note)
        self.assertIn("must now work", note)
        self.assertIn("a test must cover it", note)

    def test_a_fix_child_is_an_ordinary_child_so_the_note_names_no_flag_and_no_reuse(self):
        note = fix_note.fix_note(20)
        for word in ("issue-", "keeps", "same flag", "released again", "Preview Token"):
            self.assertNotIn(word, note)


if __name__ == "__main__":
    unittest.main()
