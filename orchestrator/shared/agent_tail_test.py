import json
import tempfile
import unittest
from pathlib import Path

from shared import agent_tail


class LastWords(unittest.TestCase):
    def write(self, lines):
        path = Path(tempfile.mkdtemp()) / "t.jsonl"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_the_last_messages_are_returned_in_order_and_cut_short(self):
        path = self.write([json.dumps({"kind": "MessageEvent", "content": f"step {i} " + "x" * 400}) for i in range(5)])
        words = agent_tail.last_words(path, count=2, width=20)
        self.assertEqual([w[:6] for w in words], ["step 3", "step 4"])
        self.assertTrue(all(len(w) == 20 for w in words))

    def test_lines_that_are_not_events_are_skipped(self):
        path = self.write(["not json", "[1]", json.dumps({"kind": "X"}), json.dumps({"thought": "check the health route"})])
        self.assertEqual(agent_tail.last_words(path), ["check the health route"])

    def test_a_missing_log_says_nothing(self):
        self.assertEqual(agent_tail.last_words_note(Path(tempfile.mkdtemp()) / "none.jsonl"), "")

    def test_the_note_names_the_messages(self):
        path = self.write([json.dumps({"message": "I could not reach the app"})])
        self.assertIn("I could not reach the app", agent_tail.last_words_note(path))


if __name__ == "__main__":
    unittest.main()
