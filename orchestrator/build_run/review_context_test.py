import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run import review_code  # noqa: E402


class Spec(unittest.TestCase):
    def test_an_update_is_reviewed_against_its_change_request_not_the_original_intake(self):
        git = lambda *a: {"diff": "D", "show": "X"}.get(a[0], "") if "--name-only" not in a else ""
        text = review_code.build_review_context(git, "base", "head", 10**6, spec="Add tags to notes")
        self.assertIn("# Change request (the spec for this change)\nAdd tags to notes", text)
        self.assertNotIn("# INTAKE.md", text)
        self.assertIn("# INTAKE.md", review_code.build_review_context(git, "base", "head", 10**6))


if __name__ == "__main__":
    unittest.main()
