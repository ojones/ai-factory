import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config  # noqa: E402

from retrospective import run_facts, run_retrospective, story_report, tracker  # noqa: E402

STATE = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass",
         "run_url": "http://run", "issue_number": "7", "spent_usd": 1.5, "commits": ["a"],
         "blocking": [{"summary": "The new route is mounted before the health route"}],
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2, "usage": {"seconds": 120, "calls": 30}},
                    {"stage": "Release", "round": "-", "verdict": "x", "cost_usd": 0, "usage": None}]}


class Bugs(unittest.TestCase):
    BUGS = [{"kind": "regression", "flag": "", "check": "GET /api/notes answers 200", "evidence": "got 404", "repro": "curl /api/notes"},
            {"kind": "dark", "flag": "pin", "check": "pin route answers 201", "evidence": "got 500", "repro": ""}]

    def facts(self, **over):
        with tempfile.TemporaryDirectory() as tmp:
            return run_facts.collect_facts(tmp, {**STATE, "outcome": "regression", "bugs": self.BUGS, **over})

    def fake_gh(self, calls, comments=""):

        def gh(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout=comments)
            return mock.Mock(stdout="[]" if args[:2] == ["issue", "list"] else "")
        return gh

    def test_the_bugs_go_on_the_stories_own_issue_and_never_into_a_new_one(self):
        calls = []
        with mock.patch.object(tracker, "gh", self.fake_gh(calls)):
            self.assertTrue(story_report.note_bugs_on_story("o/f", "tok", "7", self.facts(), carried=False))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]], "no new issue is opened for an app-side bug")
        self.assertTrue(any(c[:3] == ["issue", "edit", "7"] and "bug" in c for c in calls))
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertEqual(comment[2], "7")
        body = comment[comment.index("--body") + 1]
        self.assertIn("**GET /api/notes answers 200** (behaviour that was live before this change stopped working)", body)
        self.assertIn("Repro: curl /api/notes", body)
        self.assertIn("flag `pin`", body)

    def test_a_retry_that_already_carries_the_bugs_gets_only_the_label_not_a_second_comment(self):
        calls = []
        with mock.patch.object(tracker, "gh", self.fake_gh(calls)):
            self.assertTrue(story_report.note_bugs_on_story("o/f", "tok", "7", self.facts(), carried=True))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "comment"]])

    def test_the_notes_are_added_once_per_run_and_nothing_without_bugs(self):
        calls = []
        seen = f"<!-- bugs:{STATE['run_url']} -->"
        with mock.patch.object(tracker, "gh", self.fake_gh(calls, comments=seen)):
            self.assertFalse(story_report.note_bugs_on_story("o/f", "tok", "7", self.facts(), carried=False))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "comment"]])
        calls.clear()
        with mock.patch.object(tracker, "gh", self.fake_gh(calls)):
            self.assertFalse(story_report.note_bugs_on_story("o/f", "tok", "7", self.facts(bugs=[]), carried=False))
        self.assertEqual(calls, [])

    def run_main(self, state, target):
        work = Path(tempfile.mkdtemp())
        (work / "state.json").write_text(json.dumps(state))
        calls = []
        env = {"BUILD_RUN_DIR": str(work), "GITHUB_REPOSITORY": "o/f", "GITHUB_RUN_ID": "9", "FACTORY_PAT": "pat", "FACTORY_GH_TOKEN": "tok"}
        with mock.patch.dict(__import__("os").environ, env), mock.patch.object(tracker, "gh", self.fake_gh(calls)), \
                mock.patch.object(config, "load", return_value={"roles": {}, "limits": {}}), \
                mock.patch.object(run_retrospective.file_failure, "file_failures", return_value=[{"key": "k", "source": "build_run", "severity": "failure", "target": target,
                                                                                 "action": "bug_intake" if target == "app" else "fix_request", "url": "u"}]):
            run_retrospective.main()
        return calls

    def test_a_failed_run_notes_its_bugs_on_the_story_unless_a_bug_intake_already_carries_them(self):
        state = dict(STATE, outcome="round_limit", bugs=self.BUGS, issue_number="7", flags=["pin"])
        calls = self.run_main(state, "factory")
        story = [c for c in calls if c[:2] == ["issue", "comment"] and c[2] == "7" and "Bugs the tester saw" in c[c.index("--body") + 1]]
        self.assertEqual(len(story), 1)
        calls = self.run_main(state, "app")  # the bug Intake's requirements carry them already
        self.assertFalse([c for c in calls if c[:2] == ["issue", "comment"] and "Bugs the tester saw" in c[c.index("--body") + 1]])
        self.assertTrue(any(c[:3] == ["issue", "edit", "7"] and "bug" in c for c in calls))

    def test_the_summary_on_the_story_names_the_bugs_and_the_rollback(self):
        text = story_report.render_retrospective(self.facts(), [], [], None, [{"kind": "regression", "check": "GET /api/notes answers 200", "url": ""}])
        self.assertIn("rolled back to the previous version", text)
        self.assertIn("Bug noted on this issue (regression): GET /api/notes answers 200", text)


if __name__ == "__main__":
    unittest.main()
