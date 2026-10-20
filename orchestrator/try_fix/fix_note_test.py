import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import fix_note  # noqa: E402


class FixNote(unittest.TestCase):
    def test_the_note_names_the_failed_child_and_the_flag_it_keeps_and_how_to_test_it(self):
        note = fix_note.fix_note(12, 20)
        self.assertIn("#20", note)
        self.assertIn("`issue-12`", note)
        self.assertIn("Preview Token", note)
        self.assertIn("released again", note)


if __name__ == "__main__":
    unittest.main()
