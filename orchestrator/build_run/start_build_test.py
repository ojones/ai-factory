import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from build_run import start_build as u  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from request import intake_labels  # noqa: E402
from shared import child_tickets, github  # noqa: E402

FORM = "### App name\n\n{app}\n\n### What should change?\n\n{task}\n\n### Cost cap override (USD)\n\n{cap}\n"


def proc(stdout="", returncode=0):
    return mock.Mock(stdout=stdout, returncode=returncode, stderr="")


class GitHub(unittest.TestCase):
    def run_start(self, body, repo_json=None, repo_rc=0):
        calls = []

        def fake(args, token, check=False):
            calls.append(args)
            if args[0] == "api" and args[1].endswith("/parent"):
                return proc(json.dumps({"number": 7, "state": "open"}))
            if args[0] == "api":
                return proc(json.dumps(repo_json or {}), repo_rc)
            return proc()

        body = child_tickets.render_marker({"parent": 7, "cs": "CS-1", "kind": "update"}) + "\n\n" + body
        env = {"FACTORY_REPO": "o/f", "FACTORY_PAT": "pat", "GH_TOKEN": "t", "ISSUE_NUMBER": "9", "ISSUE_BODY": body, "RUN_URL": "u"}
        with mock.patch.dict(os.environ, env), mock.patch.object(github, "run", fake):
            return u.start(), calls

    def test_a_good_update_intake_is_labelled_dispatched_and_acknowledged(self):
        code, calls = self.run_start(FORM.format(app="notes", task="Add tags", cap=""), {"description": "Intake: o/f#3"})
        self.assertEqual(code, 0)
        dispatch = next(c for c in calls if c[:2] == ["workflow", "run"])
        self.assertIn("issue_number=9", dispatch)
        self.assertIn("app_name=notes", dispatch)
        self.assertTrue(any("app:notes" in c for c in calls if c[:2] == ["issue", "edit"]))
        self.assertTrue(any(c[:2] == ["issue", "comment"] and "accepted" in c[-1] for c in calls))

    def test_every_refusal_comments_removes_the_label_and_dispatches_nothing(self):
        cases = [(FORM.format(app="Bad Name", task="x", cap=""), {}, 0),
                 (FORM.format(app="notes", task="_No response_", cap=""), {}, 0),
                 (FORM.format(app="ghost", task="x", cap=""), {}, 1),
                 (FORM.format(app="notes", task="x", cap=""), {"description": "someone else's repo"}, 0)]
        for body, repo_json, rc in cases:
            code, calls = self.run_start(body, repo_json, rc)
            self.assertEqual(code, 1, body)
            self.assertFalse([c for c in calls if c[:2] == ["workflow", "run"]], body)
            self.assertTrue(any(c[:2] == ["issue", "comment"] and "stopped" in c[-1] for c in calls), body)
            self.assertTrue(any(c[:2] == ["issue", "edit"] and "--remove-label" in c and intake_labels.START in c for c in calls), body)


class PlannedChildrenOnly(unittest.TestCase):
    PLAN = {"description": "Intake: o/f#3"}

    def start(self, body, parent=None):
        # `parent` is {number, state} (or None) for the child's parent, answered by the sub-issues API.
        calls = []

        def fake(args, token, check=False):
            calls.append(args)
            if args[0] == "api" and args[1].endswith("/parent"):
                if parent is None:
                    return mock.Mock(stdout="", stderr="gh: No parent issue found (HTTP 404)", returncode=1)
                return proc(json.dumps(parent))
            if args[0] == "api":
                return proc(json.dumps(self.PLAN))
            return proc()

        env = {"FACTORY_REPO": "o/f", "FACTORY_PAT": "pat", "GH_TOKEN": "t", "ISSUE_NUMBER": "9", "ISSUE_BODY": body, "RUN_URL": "u"}
        with mock.patch.dict(os.environ, env), mock.patch.object(github, "run", fake):
            return u.start(), calls

    def child(self, parent=7):
        return child_tickets.render_marker({"parent": parent, "cs": "CS-1", "kind": "update"}) + "\n\n" + FORM.format(app="notes", task="Add tags", cap="")

    def test_a_planned_child_of_an_open_plan_starts(self):
        code, calls = self.start(self.child(), {"number": 7, "state": "open"})
        self.assertEqual(code, 0)
        self.assertTrue([c for c in calls if c[:2] == ["workflow", "run"]])

    def test_an_issue_with_no_marker_or_no_parent_or_a_closed_or_other_plan_does_not_start(self):
        cases = [(FORM.format(app="notes", task="x", cap=""), {"number": 7, "state": "open"}, "no plan marker"),
                 (self.child(), None, "not a sub-issue of any plan"),
                 (self.child(), {"number": 7, "state": "closed"}, "is closed"),
                 (self.child(parent=9), {"number": 7, "state": "open"}, "names #9")]
        for body, parent, why in cases:
            code, calls = self.start(body, parent)
            self.assertEqual(code, 1, why)
            self.assertFalse([c for c in calls if c[:2] == ["workflow", "run"]], why)
            self.assertTrue(any(c[:2] == ["issue", "comment"] and why in c[-1] for c in calls), why)

    def test_a_lookup_that_fails_refuses_instead_of_starting(self):
        def broken(args, token, check=False):
            if args[0] == "api" and args[1].endswith("/parent"):
                return mock.Mock(stdout="", stderr="HTTP 500", returncode=1)
            return proc(json.dumps(self.PLAN)) if args[0] == "api" else proc()
        env = {"FACTORY_REPO": "o/f", "FACTORY_PAT": "pat", "GH_TOKEN": "t", "ISSUE_NUMBER": "9", "ISSUE_BODY": self.child(), "RUN_URL": "u"}
        with mock.patch.dict(os.environ, env), mock.patch.object(github, "run", broken):
            self.assertEqual(u.start(), 1)


if __name__ == "__main__":
    unittest.main()
