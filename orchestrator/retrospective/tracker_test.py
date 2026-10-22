import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import tracker  # noqa: E402

STATE = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass",
         "run_url": "http://run", "issue_number": "7", "spent_usd": 1.5, "commits": ["a"],
         "blocking": [{"summary": "The new route is mounted before the health route"}],
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2, "usage": {"seconds": 120, "calls": 30}},
                    {"stage": "Release", "round": "-", "verdict": "x", "cost_usd": 0, "usage": None}]}


class Recurrence(unittest.TestCase):
    ISSUES = [{"number": 4, "title": "Lesson [many_rounds] aa", "state": "CLOSED"},
              {"number": 9, "title": "Lesson [budget_high] bb", "state": "OPEN"},
              {"number": 5, "title": "Lesson [many_rounds] aa", "state": "OPEN"}]

    def test_open_beats_closed_and_only_exact_titles_match(self):
        self.assertEqual(tracker.pick_existing(self.ISSUES, "Lesson [many_rounds] aa"), (5, 4))
        self.assertEqual(tracker.pick_existing(self.ISSUES, "Lesson [budget_high] bb"), (9, None))
        self.assertEqual(tracker.pick_existing(self.ISSUES, "Lesson [slow_stage] cc"), (None, None))
        self.assertEqual(tracker.pick_existing([{"number": 1, "title": "Lesson [x] y", "state": "closed"}], "Lesson [x] y"), (None, 1))


class SightingCount(unittest.TestCase):
    def test_a_sighting_is_counted_once_per_run_and_apps_are_counted_apart(self):
        body, runs, apps = tracker.with_sighting("A lesson.", "https://x/runs/1", "todo")
        self.assertEqual((runs, apps), (1, 1))
        again, runs, apps = tracker.with_sighting(body, "https://x/runs/1", "todo")
        self.assertEqual((again, runs, apps), (body, 1, 1), msg="the same run reported twice changes nothing")
        body, runs, apps = tracker.with_sighting(body, "https://x/runs/2", "notes")
        self.assertEqual((runs, apps), (2, 2))
        self.assertEqual(body.count("<!-- seen:"), 1)
        self.assertEqual(tracker.sightings(body), {"https://x/runs/1": "todo", "https://x/runs/2": "notes"})
        self.assertEqual(tracker.sightings("no marker"), {})

    def test_a_failed_read_never_overwrites_the_issue_body(self):
        calls = []

        def gh(args, token, check=False):
            calls.append(args[1])
            if check:
                raise RuntimeError("gh issue view failed")
            return mock.Mock(stdout="")
        with mock.patch.object(tracker, "gh", gh), self.assertRaises(RuntimeError):
            tracker.note_sighting("o/f", "t", 7, {"run_url": "https://x/runs/1", "app": "todo"}, 2)
        self.assertEqual(calls, ["view"])

    def test_promotion_waits_for_enough_distinct_runs_unless_severe(self):
        self.assertFalse(tracker.ready_for_fix(1, 2))
        self.assertTrue(tracker.ready_for_fix(2, 2))
        self.assertTrue(tracker.ready_for_fix(1, 2, severe=True))
        self.assertTrue(tracker.ready_for_fix(1, 1))
        self.assertTrue(tracker.ready_for_fix(1, 0))

    def test_noting_a_sighting_edits_the_body_and_labels_it_recurring_at_the_threshold(self):
        body = {"body": "A lesson."}
        calls = []

        def fake_gh(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout=json.dumps(body))
            if args[:2] == ["issue", "edit"]:
                body["body"] = args[args.index("--body") + 1]
            return mock.Mock(stdout="")
        with mock.patch.object(tracker, "gh", fake_gh):
            self.assertEqual(tracker.note_sighting("o/f", "t", 5, {"run_url": "https://x/runs/1", "app": "a"}, 2), 1)
            self.assertNotIn("--add-label", calls[-1])
            self.assertEqual(tracker.note_sighting("o/f", "t", 5, {"run_url": "https://x/runs/2", "app": "a"}, 2), 2)
            self.assertIn("recurring", calls[-1])


if __name__ == "__main__":
    unittest.main()
