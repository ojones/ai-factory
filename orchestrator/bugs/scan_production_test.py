import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from request import find_intakes  # noqa: E402
from shared import github  # noqa: E402
from try_fix import event  # noqa: E402

from bugs import escaped_defects, scan_logs, scan_production  # noqa: E402

CFG = {"enabled": True, "min_occurrences": 3, "max_per_app_per_day": 2}
TODAY = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())


def log_of(message, n, **extra):
    return "\n".join("2026-10-13T01:00:00Z app[abc] iad [info] " + json.dumps({"level": "error", "message": message, **extra}) for _ in range(n))


class Scan(unittest.TestCase):
    def go(self, logs="", bugs=(), defects=(), state=None):
        calls = []

        def intakes(repo, token, app, label, state_="open"):
            return [b for b in bugs if state_ == "all" or b.get("open", True)]

        def run(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps([{"body": "<!-- factory-data:" + json.dumps(state) + " -->"}] if state else []))
            return mock.Mock(stdout="")
        with mock.patch.object(find_intakes, "intakes_with", intakes), mock.patch.object(github, "run", run), \
                mock.patch.object(escaped_defects, "owner_defects", lambda repo, pat, app: list(defects)):
            events = scan_production.scan_app("o/ai-factory", "tok", "pat", "demo", CFG, lambda app: logs)
        return events, calls

    def test_a_repeated_error_becomes_one_failure_event_and_nothing_is_filed_here(self):
        events, calls = self.go(log_of("todo 5 missing", 4))
        self.assertEqual([(e["source"], e["severity"]) for e in events], [("production_feedback", "failure")])
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])

    def test_an_error_below_the_threshold_is_not_an_event(self):
        self.assertEqual(self.go(log_of("todo 5 missing", 2))[0], [])

    def test_an_error_with_an_open_bug_only_adds_a_comment_with_the_count(self):
        fp = scan_logs.fingerprint({"message": "todo 5 missing"})
        key = event.event_key("production_feedback", "demo", fp)
        events, calls = self.go(log_of("todo 5 missing", 5), bugs=[{"number": 40, "title": f"demo: x [{key}]", "createdAt": TODAY}])
        self.assertEqual(events, [])
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertEqual(comment[2], "40")
        self.assertIn("Seen 5 more times", comment[comment.index("--body") + 1])

    def test_another_open_bug_for_the_app_holds_new_errors_back(self):
        self.assertEqual(self.go(log_of("todo 5 missing", 5), bugs=[{"number": 41, "title": "demo: other [abc]", "createdAt": "2020-01-01T00:00:00Z"}])[0], [])

    def test_the_daily_limit_holds_new_errors_back(self):
        old_open = [{"number": n, "title": f"demo: t [k{n}]", "createdAt": TODAY, "open": False} for n in (50, 51)]
        self.assertEqual(self.go(log_of("todo 5 missing", 5), bugs=old_open)[0], [])

    def test_an_owner_defect_comes_first_and_the_logs_wait(self):
        events, _ = self.go(log_of("todo 5 missing", 5), defects=[{"number": 5, "title": "Delete loses data", "body": "steps"}])
        self.assertEqual([(e["source"], e["fingerprint"]) for e in events], [("escaped_defect", "d5")])

    def test_a_defect_already_reported_is_not_reported_again_even_if_its_bug_is_closed(self):
        ev = event.make("escaped_defect", "failure", "demo", "x", "d5")
        closed = [{"number": 60, "title": f"demo: reported defect [{ev['key']}]", "createdAt": "2020-01-01T00:00:00Z", "open": False}]
        events, _ = self.go(defects=[{"number": 5, "title": "Delete loses data", "body": ""}], bugs=closed)
        self.assertEqual(events, [])

    def test_an_error_that_names_a_dark_flag_in_the_app_state_is_tied_to_that_story(self):
        state = {"flags": [{"key": "demo.feature.issue-20", "state": "switched off by the watchdog"}]}
        events, _ = self.go(log_of("TypeError", 4, flag="demo.feature.issue-20"), state=state)
        self.assertEqual((events[0]["story"], events[0]["released"], events[0]["flag"]), (20, False, "issue-20"))

    def test_one_events_file_is_written_and_a_switched_off_scan_writes_an_empty_one(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "o/ai-factory", "FACTORY_GH_TOKEN": "t", "FACTORY_PAT": "p"}), \
                mock.patch.object(scan_production.config, "load", return_value={"limits": {"production_feedback": {"enabled": False}}}):
            path = Path(tmp) / "events.json"
            self.assertEqual(scan_production.main(["x", str(path)]), 0)
            self.assertEqual(json.loads(path.read_text()), [])


if __name__ == "__main__":
    unittest.main()
