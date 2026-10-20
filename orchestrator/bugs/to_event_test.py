import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import event  # noqa: E402

from bugs import to_event  # noqa: E402

GROUP = {"count": 4, "message": "bad N", "frame": "routes/todos.js", "sample": "{}"}


class ErrorEvent(unittest.TestCase):
    def test_an_error_is_a_failure_event_with_only_the_cleaned_message_and_the_frame(self):
        ev = to_event.error_event("todo", "abc12345", GROUP)
        self.assertTrue(event.valid(ev))
        self.assertEqual((ev["source"], ev["severity"], ev["app"], ev["fingerprint"]), ("production_feedback", "failure", "todo", "abc12345"))
        self.assertIn("routes/todos.js", ev["summary"])
        self.assertIn("bad N", ev["summary"])
        self.assertIn("4 times", ev["evidence"])

    def test_the_key_does_not_depend_on_how_often_it_happened(self):
        a = to_event.error_event("todo", "abc12345", GROUP)
        b = to_event.error_event("todo", "abc12345", dict(GROUP, count=99))
        self.assertEqual(a["key"], b["key"])

    def test_an_error_that_names_a_flag_in_the_app_state_is_tied_to_its_story(self):
        ev = to_event.error_event("todo", "abc12345", GROUP, "evaluating issue-20", {20: "dark"})
        self.assertEqual((ev["story"], ev["flag"], ev["released"]), (20, "issue-20", False))
        plain = to_event.error_event("todo", "abc12345", GROUP, "nothing", {20: "dark"})
        self.assertEqual((plain["story"], plain["flag"], plain["released"]), (None, None, None))


class DefectEvent(unittest.TestCase):
    def test_a_defect_is_one_event_per_issue_however_often_it_is_read(self):
        issue = {"number": 5, "title": "  Delete loses data ", "body": "steps " * 600}
        a, b = to_event.defect_event("todo", issue), to_event.defect_event("todo", dict(issue, body="other"))
        self.assertEqual(a["key"], b["key"])
        self.assertEqual((a["source"], a["severity"], a["fingerprint"]), ("escaped_defect", "failure", "d5"))
        self.assertTrue(a["summary"].startswith("reported defect: Delete loses data"))
        self.assertLessEqual(len(a["evidence"]), event.MAX_TEXT)


if __name__ == "__main__":
    unittest.main()
