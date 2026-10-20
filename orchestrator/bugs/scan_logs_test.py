import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bugs import scan_logs  # noqa: E402


def line(msg, level="error", **extra):
    return "2026-10-13T01:00:00Z app[abc] iad [info] " + json.dumps({"level": level, "message": msg, **extra})


class Events(unittest.TestCase):
    def test_only_error_and_fatal_json_lines_count(self):
        text = "\n".join([line("boom"), line("fine", "info"), "not json {oops", line("dead", "fatal"), "plain text line"])
        self.assertEqual([e["message"] for e in scan_logs.parse_events(text)], ["boom", "dead"])

    def test_ids_and_numbers_do_not_split_an_error(self):
        a = {"message": "todo 17 not found for user 9f1c2a3b-1111-2222-3333-444455556666"}
        b = {"message": "todo 4021 not found for user 0a0a0a0a-1111-2222-3333-444455556666"}
        self.assertEqual(scan_logs.fingerprint(a), scan_logs.fingerprint(b))
        self.assertNotEqual(scan_logs.fingerprint(a), scan_logs.fingerprint({"message": "something else"}))

    def test_the_first_application_frame_is_used_not_node_modules(self):
        stack = "Error: x\n    at f (/app/node_modules/express/lib/router.js:10:3)\n    at g (/app/dist/routes/todos.js:42:9)"
        self.assertEqual(scan_logs.first_frame({"stack": stack}), "routes/todos.js")
        self.assertEqual(scan_logs.first_frame({"message": "no stack"}), "")

    def test_the_same_message_from_two_places_is_two_errors(self):
        a = {"message": "failed", "stack": "at a (/app/dist/a.js:1:1)"}
        b = {"message": "failed", "stack": "at b (/app/dist/b.js:1:1)"}
        self.assertNotEqual(scan_logs.fingerprint(a), scan_logs.fingerprint(b))

    def test_group_counts_occurrences_and_keeps_the_first_raw_entry(self):
        g = scan_logs.group(scan_logs.parse_events("\n".join(line(f"todo {i} missing") for i in range(4))))
        self.assertEqual([v["count"] for v in g.values()], [4])
        self.assertIn("todo 0 missing", next(iter(g.values()))["sample"])

    def test_the_message_is_clipped(self):
        self.assertLessEqual(len(scan_logs.clean_message({"message": "x" * 5000})), scan_logs.CLIP)


if __name__ == "__main__":
    unittest.main()
