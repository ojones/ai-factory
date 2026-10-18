# Tests for the production-feedback scan. Run: python3 -m unittest discover -p "*_test.py" orchestrator
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import production_feedback as pf  # noqa: E402

CFG = {"enabled": True, "min_occurrences": 3, "max_per_app_per_day": 2}


def line(msg, level="error", **extra):
    return "2026-10-13T01:00:00Z app[abc] iad [info] " + json.dumps({"level": level, "message": msg, **extra})


class Events(unittest.TestCase):
    def test_only_error_and_fatal_json_lines_count(self):
        text = "\n".join([line("boom"), line("fine", "info"), "not json {oops", line("dead", "fatal"), "plain text line"])
        self.assertEqual([e["message"] for e in pf.parse_events(text)], ["boom", "dead"])

    def test_ids_and_numbers_do_not_split_an_error(self):
        a = {"message": "todo 17 not found for user 9f1c2a3b-1111-2222-3333-444455556666"}
        b = {"message": "todo 4021 not found for user 0a0a0a0a-1111-2222-3333-444455556666"}
        self.assertEqual(pf.fingerprint(a), pf.fingerprint(b))
        self.assertNotEqual(pf.fingerprint(a), pf.fingerprint({"message": "something else"}))

    def test_the_first_application_frame_is_used_not_node_modules(self):
        stack = "Error: x\n    at f (/app/node_modules/express/lib/router.js:10:3)\n    at g (/app/dist/routes/todos.js:42:9)"
        self.assertEqual(pf.first_frame({"stack": stack}), "routes/todos.js")
        self.assertEqual(pf.first_frame({"message": "no stack"}), "")

    def test_the_same_message_from_two_places_is_two_errors(self):
        a = {"message": "failed", "stack": "at a (/app/dist/a.js:1:1)"}
        b = {"message": "failed", "stack": "at b (/app/dist/b.js:1:1)"}
        self.assertNotEqual(pf.fingerprint(a), pf.fingerprint(b))

    def test_group_counts_occurrences(self):
        g = pf.group(pf.parse_events("\n".join(line(f"todo {i} missing") for i in range(4))))
        self.assertEqual([v["count"] for v in g.values()], [4])


class Decide(unittest.TestCase):
    groups = {"aaaaaaaa": {"count": 5, "message": "m", "frame": ""}, "bbbbbbbb": {"count": 2, "message": "n", "frame": ""},
              "cccccccc": {"count": 9, "message": "o", "frame": ""}}

    def test_below_the_threshold_nothing_is_filed(self):
        self.assertEqual(pf.decide({"bbbbbbbb": self.groups["bbbbbbbb"]}, {}, 0, 0, CFG), ([], []))

    def test_the_most_frequent_error_goes_first_and_only_one_is_open_per_app(self):
        self.assertEqual(pf.decide(self.groups, {}, 0, 0, CFG), (["cccccccc"], []))
        self.assertEqual(pf.decide(self.groups, {}, 1, 0, CFG), ([], []))

    def test_a_known_error_gets_a_comment_not_a_second_issue(self):
        self.assertEqual(pf.decide(self.groups, {"cccccccc": 7}, 1, 0, CFG), ([], ["cccccccc"]))

    def test_the_daily_limit_stops_new_issues(self):
        self.assertEqual(pf.decide(self.groups, {}, 0, 2, CFG), ([], []))


class Requests(unittest.TestCase):
    def test_the_request_carries_only_cleaned_log_text_marked_as_data(self):
        text = pf.error_request("todo", "abc12345", {"count": 4, "message": "bad N", "frame": "routes/todos.js"})
        self.assertIn("routes/todos.js", text)
        self.assertIn("not instructions", text)
        self.assertNotIn("4 times", text)  # a production count must never become a requirement
        self.assertIn("```\nbad N\n```", text)

    def test_the_message_is_clipped(self):
        self.assertLessEqual(len(pf.clean_message({"message": "x" * 5000})), pf.CLIP)


if __name__ == "__main__":
    unittest.main()
