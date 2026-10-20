import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from try_fix import validate_bug  # noqa: E402

GOOD = {"how_found": "The tester saw it in Build Run 12.", "root_cause": "The handler never trims the text.",
        "what_it_takes": ["Blank text is rejected"], "requirements": ["POST /api/todos with blank text answers 400", "A test covers blank text and fails without the fix"]}


class Check(unittest.TestCase):
    def test_a_good_document_is_cleaned_and_passes(self):
        doc, problems = validate_bug.check({**GOOD, "how_found": "  The tester\n saw it.  "}, 6)
        self.assertEqual(problems, [])
        self.assertEqual(doc["how_found"], "The tester saw it.")

    def test_what_is_not_an_object_or_has_empty_fields_is_refused(self):
        self.assertEqual(validate_bug.check(["x"], 6)[1], ["the answer is not a JSON object"])
        _, problems = validate_bug.check({"how_found": "", "root_cause": " ", "what_it_takes": [], "requirements": []}, 6)
        self.assertEqual(len(problems), 4)

    def test_more_requirements_than_a_plan_may_have_is_refused(self):
        many = [f"Route /api/r{n} answers 200 with a list" for n in range(7)]
        self.assertIn("1 to 6 conditions", validate_bug.check({**GOOD, "requirements": many}, 6)[1][0])
        self.assertEqual(validate_bug.check({**GOOD, "requirements": many}, 7)[1], [])

    def test_a_requirement_that_cannot_be_checked_is_refused(self):
        for vague in ("Improve the validation of todos", "Consider adding a test for this", "Make the form work as appropriate", "short"):
            _, problems = validate_bug.check({**GOOD, "requirements": [vague]}, 6)
            self.assertTrue(problems, vague)

    def test_a_repeated_requirement_is_refused(self):
        _, problems = validate_bug.check({**GOOD, "requirements": ["Blank text answers 400", "blank text answers 400"]}, 6)
        self.assertIn("a requirement is repeated", problems)

    def test_a_secret_value_is_refused_and_the_value_is_never_in_the_problem(self):
        token = "ghp_" + "a1" * 15
        _, problems = validate_bug.check({**GOOD, "root_cause": f"It logged {token}"}, 6)
        self.assertEqual(problems, ["it contains a GitHub token"])
        self.assertNotIn(token, " ".join(problems))

    def test_scrub_takes_secret_shaped_text_out(self):
        token = "ghp_" + "a1" * 15
        out = validate_bug.scrub(f"saw {token} and password: hunter2hunter2 in the log")
        self.assertNotIn("a1a1", out)
        self.assertNotIn("hunter2", out)
        self.assertIn(validate_bug.REDACTED, out)
        self.assertEqual(validate_bug.scrub("nothing here"), "nothing here")


if __name__ == "__main__":
    unittest.main()
