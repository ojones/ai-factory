import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from try_fix import event  # noqa: E402


class FailureEvent(unittest.TestCase):
    def test_the_key_is_stable_for_the_same_source_app_and_fingerprint_and_differs_otherwise(self):
        a = event.make("tester", "warning", "demo", "check failed", ["dark", "x"])
        self.assertEqual(a["key"], event.make("tester", "warning", "demo", "reworded", ["dark", "x"])["key"])
        self.assertNotEqual(a["key"], event.make("reviewer", "warning", "demo", "check failed", ["dark", "x"])["key"])
        self.assertNotEqual(a["key"], event.make("tester", "warning", "other", "check failed", ["dark", "x"])["key"])

    def test_text_is_collapsed_and_cut_and_the_story_is_a_number(self):
        e = event.make("build_run", "failure", "demo", "a\n  b " + "x" * 900, "f", story="66")
        self.assertTrue(e["summary"].startswith("a b "))
        self.assertLessEqual(len(e["summary"]), event.MAX_TEXT)
        self.assertEqual(e["story"], 66)

    def test_an_unknown_source_or_severity_is_refused(self):
        for source, severity in (("mystery", "failure"), ("tester", "fatal")):
            with self.assertRaises(ValueError):
                event.make(source, severity, "demo", "x", "f")

    def test_events_round_trip_through_a_file_and_malformed_ones_are_dropped(self):
        good = event.make("staging", "failure", "demo", "smoke failed", "smoke")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            event.dump([good, {"severity": "failure"}, "junk"], path)
            self.assertEqual(event.load(path), [good])
            path.write_text("not json")
            self.assertEqual(event.load(path), [])
            self.assertEqual(event.load(Path(tmp) / "missing.json"), [])


if __name__ == "__main__":
    unittest.main()
