"""Tests for the ui-check helper: pure logic always, a real browser run only where Playwright is installed.
Run: python3 -m unittest discover orchestrator"""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_check as u  # noqa: E402

try:
    import playwright  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

BTN = {"role": "button", "name": "Add"}
PAGE = """<!doctype html><title>Notes</title><main><h1>Notes</h1>
<label for=t>New note</label><input id=t>
<button onclick="var li=document.createElement('li');li.textContent=document.getElementById('t').value;document.getElementById('l').appendChild(li)">Add</button>
<ul id=l></ul>%s</main>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        preview = "preview=TKN9f3a1c" in self.headers.get("Cookie", "")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        if "preview=TKN9f3a1c" in self.path:
            self.send_header("Set-Cookie", "preview=TKN9f3a1c; HttpOnly; Path=/")
        self.end_headers()
        self.wfile.write((PAGE % ("<button>Secret flagged control</button>" if preview else "")).encode())


class Logic(unittest.TestCase):
    def test_validate_rules(self):
        ok = {"id": "a", "start": "/", "steps": [{"click": BTN}], "expect": {"visible": [BTN]}}
        self.assertIsNone(u.validate([ok])[1])
        for bad in ({**ok, "id": ""}, {**ok, "expect": {}}, {**ok, "start": "https://evil.example/"}, {**ok, "start": "//evil.example"},
                    {**ok, "steps": [{"goto": "http://evil.example"}]}, {**ok, "steps": [{"click": {"role": "button", "label": "x"}}]},
                    {**ok, "steps": [{"fill": {"label": "x"}}]}, {**ok, "steps": [{"dance": 1}]}, {**ok, "steps": [{"press": "a"}] * 25}):
            self.assertIsNotNone(u.validate([bad])[1], bad)
        self.assertIsNotNone(u.validate([ok, ok])[1])
        self.assertIsNotNone(u.validate([])[1])

    def test_compare_flags_each_kind_of_difference(self):
        obs = {"visible": {u.loc_key(BTN): True}, "text": {u.loc_key({"text": "Hi"}): "Hello there"}, "count": {u.loc_key({"role": "listitem"}): 2},
               "url_path": "/", "title": "Notes", "console_errors": ["boom"]}
        self.assertEqual(u.compare({"visible": [BTN], "text": [{"text": "Hi", "contains": "Hello"}], "count": [{"role": "listitem", "is": 2}],
                                    "url_path": "/", "title_contains": "Not"}, obs), [])
        for expect in ({"hidden": [BTN]}, {"visible": [{"label": "missing"}]}, {"text": [{"text": "Hi", "equals": "Hello"}]},
                       {"text": [{"text": "gone", "contains": "x"}]}, {"count": [{"role": "listitem", "is": 3}]}, {"url_path": "/x"},
                       {"title_contains": "Other"}, {"no_console_errors": True}):
            self.assertEqual(len(u.compare(expect, obs)), 1, expect)

    def test_the_token_is_scrubbed_from_text_and_urls(self):
        self.assertNotIn("secret123", u.scrub("went to /?preview=secret123 and secret123 again", "secret123"))
        self.assertNotIn("abc", u.scrub("/x?a=1&preview=abc", None))


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright is not installed here")
class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_a_form_works_a_flagged_control_follows_the_token_and_a_wrong_expectation_fails_with_a_screenshot(self):
        tmp = Path(tempfile.mkdtemp())
        log = tmp / "log.jsonl"
        item = {"role": "listitem"}
        checks = [
            {"id": "add", "name": "Adding shows the note", "steps": [{"fill": {"label": "New note", "value": "factory-test-a"}}, {"click": BTN}],
             "expect": {"text": [{**item, "contains": "factory-test-a"}], "count": [{**item, "is": 1}], "title_contains": "Notes"}},
            {"id": "dark", "name": "No flagged control without the token", "auth": "none", "expect": {"hidden": [{"role": "button", "name": "Secret flagged control"}]}},
            {"id": "lit", "name": "The flagged control shows with the token", "auth": "preview", "expect": {"visible": [{"role": "button", "name": "Secret flagged control"}]}},
            {"id": "wrong", "name": "A wrong expectation", "auth": "none", "expect": {"visible": [{"role": "button", "name": "Secret flagged control"}]}},
        ]
        results = u.run_checks(checks, self.base, "TKN9f3a1c", str(log), str(tmp))
        self.assertEqual([r["ok"] for r in results], [True, True, True, False])
        self.assertIn("visible", results[3]["problems"][0])
        self.assertTrue((tmp / results[3]["screenshot"]).exists())
        self.assertEqual(len(log.read_text().splitlines()), 4)
        self.assertNotIn("TKN9f3a1c", log.read_text())

    def test_other_origins_are_never_requested_and_a_missing_token_fails(self):
        r = u.run_checks([{"id": "x", "auth": "preview", "expect": {"visible": [BTN]}}], self.base, None)
        self.assertFalse(r[0]["ok"])
        self.assertIn("PREVIEW_TOKEN", r[0]["problems"][0])


if __name__ == "__main__":
    unittest.main()
