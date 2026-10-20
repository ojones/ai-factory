import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import http_client, model_call  # noqa: E402


class JsonChat(unittest.TestCase):
    def test_it_posts_the_messages_asks_for_json_and_returns_the_parsed_object(self):
        seen = {}

        def request(method, url, key, body=None, timeout=None):
            seen.update(method=method, url=url, key=key, body=body, timeout=timeout)
            return 200, {"choices": [{"message": {"content": '{"a": 1}'}}]}
        with mock.patch.object(http_client, "request", request):
            self.assertEqual(model_call.json_chat("https://p", "k", "m", "sys", "usr", timeout=9), {"a": 1})
        self.assertEqual((seen["method"], seen["url"], seen["key"], seen["timeout"]), ("POST", "https://p/chat/completions", "k", 9))
        self.assertEqual(seen["body"]["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in seen["body"]["messages"]], ["system", "user"])

    def test_a_non_200_answer_and_a_non_json_answer_both_raise(self):
        with mock.patch.object(http_client, "request", lambda *a, **k: (500, {})):
            with self.assertRaises(RuntimeError):
                model_call.json_chat("https://p", "k", "m", "s", "u")
        with mock.patch.object(http_client, "request", lambda *a, **k: (200, {"choices": [{"message": {"content": "no"}}]})):
            with self.assertRaises(ValueError):
                model_call.json_chat("https://p", "k", "m", "s", "u")


if __name__ == "__main__":
    unittest.main()
