import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from shared import api_check as a


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if self.headers.get("X-Preview-Token") != "tok":
            return self._send(404, {"error": "nope"})
        self._send(200, {"id": 7, "text": json.loads(self.rfile.read(n))["text"], "echo": self.headers.get("X-Preview-Token")})

    def do_GET(self):
        self._send(200, {"items": [{"id": 7}]} if self.path == "/api/notes" else {"id": 7})


class Logic(unittest.TestCase):
    def test_subset_match_and_types(self):
        self.assertEqual(a.mismatches({"id": "<integer>", "t": "a"}, {"id": 3, "t": "a", "extra": 1}), [])
        self.assertTrue(a.mismatches({"id": "<integer>"}, {"id": True}), msg="a boolean is not an integer")
        self.assertTrue(a.mismatches({"t": "a"}, {"t": "b"}))
        self.assertTrue(a.mismatches({"t": "a"}, {}))
        self.assertTrue(a.mismatches([1, 2], [1]))

    def test_a_refusal_for_a_credential_is_blocked_unless_the_spec_expects_it(self):
        self.assertTrue(a.wants_credential({"status": 422}, 401))
        self.assertTrue(a.wants_credential({"status": [200, 202]}, 403))
        self.assertFalse(a.wants_credential({"status": 401}, 401))
        self.assertFalse(a.wants_credential({"status": [401, 403]}, 403))
        self.assertFalse(a.wants_credential({"status": 200}, 404))
        self.assertFalse(a.wants_credential({"json": {}}, 401))

    def test_status_may_be_a_list(self):
        self.assertEqual(a.compare({"status": [200, 201]}, 201, "", None, {}), [])
        self.assertTrue(a.compare({"status": 201}, 200, "", None, {}))

    def test_body_and_header_rules(self):
        self.assertTrue(a.compare({"body_not_contains": ["stack"]}, 200, "a stack trace", None, {}))
        self.assertTrue(a.compare({"header_absent": ["X-Secret"]}, 200, "", None, {"x-secret": "1"}))
        self.assertEqual(a.compare({"headers": {"content-type": "json"}}, 200, "", None, {"Content-Type": "application/json"}), [])

    def test_substitute_and_dig(self):
        self.assertEqual(a.substitute({"p": "/n/{id}", "q": "{nope}"}, {"id": 5}), {"p": "/n/5", "q": "{nope}"})
        self.assertEqual(a.dig({"items": [{"id": 9}]}, "items.0.id"), 9)

    def test_validate_refuses_other_hosts_duplicates_and_empty_expectations(self):
        ok = {"id": "a", "request": {"path": "/x"}, "expect": {"status": 200}}
        self.assertEqual(a.validate([ok])[1], None)
        self.assertIsNotNone(a.validate([ok, ok])[1])
        self.assertIsNotNone(a.validate([{**ok, "request": {"path": "https://evil.example/x"}}])[1])
        self.assertIsNotNone(a.validate([{**ok, "request": {"path": "//evil.example"}}])[1])
        self.assertIsNotNone(a.validate([{**ok, "expect": {}}])[1])
        self.assertIsNotNone(a.validate([])[1])


class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_the_helper_catches_a_wrong_status_logs_it_and_never_logs_the_token(self):
        log = Path(tempfile.mkdtemp()) / "log.jsonl"
        checks = [{"id": "create", "request": {"method": "POST", "path": "/api/notes", "auth": "preview", "json": {"text": "a"}},
                   "expect": {"status": 201, "json": {"text": "a"}}, "capture": {"nid": "id"}},
                  {"id": "get", "request": {"path": "/api/notes/{nid}"}, "expect": {"status": 200, "json": {"id": 7}}},
                  {"id": "anon", "request": {"method": "POST", "path": "/api/notes", "auth": "none", "json": {"text": "a"}},
                   "expect": {"status": 404}}]
        results = a.run_checks(checks, self.base, "tok", str(log))
        self.assertEqual([r["ok"] for r in results], [False, True, True])
        self.assertIn("expected 201, got 200", results[0]["problems"][0])
        lines = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([x["id"] for x in lines], ["create", "get", "anon"])
        self.assertNotIn("tok", log.read_text().replace('"text"', ""), msg="echoed token is scrubbed from the logged body")

    def test_a_preview_check_without_a_token_fails_instead_of_passing(self):
        r = a.run_checks([{"id": "c", "request": {"path": "/x", "auth": "preview"}, "expect": {"status": 200}}], self.base, None)
        self.assertFalse(r[0]["ok"])

    def test_an_unreachable_host_is_a_failure(self):
        r = a.run_checks([{"id": "c", "request": {"path": "/x"}, "expect": {"status": 200}}], "http://127.0.0.1:9", None)
        self.assertFalse(r[0]["ok"])


if __name__ == "__main__":
    unittest.main()
