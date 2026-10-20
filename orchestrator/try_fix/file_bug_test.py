import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import child_tickets, github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from try_fix import event, file_bug, render_bug  # noqa: E402

FORM = "### App name\n\ndemo\n\n### What should change?\n\nChange set CS-1: Tags\n\nAcceptance criteria:\n- tags work\n"
MARKER = {"parent": 7, "cs": "CS-1", "kind": "update", "flag": True, "internal_only": False, "size": "S", "requirements": ["REQ-1"]}
DOC = {"how_found": "The tester saw it.", "root_cause": "No trimming.", "what_it_takes": ["Blank text is rejected"],
       "requirements": ["POST /api/todos with blank text answers 400", "A test covers it"], "source": "agent"}


def verdict(story=12, released=False, target="managed_app", source="build_run", severity="failure", fp="fp"):
    ev = event.make(source, severity, "demo", "round limit reached", fp, story=story)
    ev["released"] = released
    return {"key": ev["key"], "verdict": "fix", "target": target, "cause": "spec_ambiguity", "reason": "r", "event": ev}


class Filing(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        self.gh.add(7)
        self.failed = self.gh.add(12, body=child_tickets.render_marker(MARKER) + "\n\n" + FORM, labels=["update-app-intake", "app:demo"])
        self.gh.issues[12]["title"] = "demo: Tags"
        self.gh.subs[7] = [12]

    def file(self, v=None, doc=DOC, max_attempts=2):
        with mock.patch.object(github, "run", self.gh), mock.patch.object(github, "ensure_label"):
            return file_bug.file_bug("o/f", "tok", "the-pat", v or verdict(), doc, {"run_url": "https://x/run/1"}, max_attempts)

    def labels(self, n):
        return {x["name"] for x in self.gh.issues[n]["labels"]}

    def edits(self, with_label):
        return [c for c in self.gh.calls if isinstance(c, list) and c[:2] == ["issue", "edit"] and with_label in c]

    def test_a_dark_story_gets_a_bug_intake_with_the_fix_for_marker_and_the_failed_child_waits_for_it(self):
        got = self.file()
        bug = got["number"]
        self.assertEqual(got["action"], "bug_intake")
        fix = child_tickets.read_fix_for(self.gh.issues[bug]["body"])
        self.assertEqual(fix, {"fix_for": 12, "flag_story": 12, "origin_parent": 7, "flag": True, "attempt": 1})
        self.assertEqual(self.gh.blocked, {12: [bug]})  # blocked by the Intake: it resumes only when the Intake closes
        self.assertIn("waiting-on-plan", self.labels(12))
        self.assertIn("Change set CS-1: Tags", self.gh.issues[bug]["body"])  # the failed child's own instructions travel with the fix
        self.assertEqual(render_bug.read_key(self.gh.issues[bug]["body"]), verdict()["key"])

    def test_planning_starts_last_with_the_pat_and_the_failed_child_is_never_started(self):
        bug = self.file()["number"]
        created_with = [c for c in self.gh.calls if isinstance(c, list) and c[:2] == ["issue", "create"]][0]
        self.assertNotIn("update-app-intake", created_with[created_with.index("--label") + 1])  # not yet: the block comes first
        self.assertIn("update-app-intake", self.labels(bug))
        self.assertEqual([c[2] for c in self.edits("update-app-intake")], [str(bug)])
        self.assertEqual(self.edits("proceed-with-change"), [])  # nobody starts the failed child again

    def test_the_story_hears_about_the_failure_and_the_bug_once(self):
        self.file()
        self.file(verdict(fp="other"))  # a second event on the same story
        notes = self.gh.comments[12]
        self.assertEqual(len([n for n in notes if "bug-comment" in n]), 2)
        first = verdict()["key"]
        self.assertEqual(len([n for n in notes if f"bug-comment:{first}" in n]), 1)
        self.assertTrue(any("Fix first" in n for n in notes))

    def test_a_repeat_of_the_same_event_comments_on_the_open_bug_and_files_nothing(self):
        first = self.file()["number"]
        again = self.file()
        self.assertEqual((again["action"], again["number"]), ("again", first))
        self.assertEqual(len([n for n, i in self.gh.issues.items() if "[" in i.get("title", "")]), 1)
        self.assertTrue(any("Seen again" in c for c in self.gh.comments[first]))

    def test_a_fix_of_a_fix_is_the_next_attempt_behind_the_original_storys_flag(self):
        first = self.file()["number"]
        fixed = self.gh.add(30, body=child_tickets.render_marker({**MARKER, "flag_story": 12, "fix_for": 12, "fix_attempt": 1}) + "\n\n" + FORM,
                            labels=["update-app-intake"])
        self.gh.issues[fixed]["title"] = "demo: Fix tags"
        self.gh.subs[first] = [fixed]
        got = self.file(verdict(story=fixed, fp="again"))
        fix = child_tickets.read_fix_for(self.gh.issues[got["number"]]["body"])
        self.assertEqual((fix["fix_for"], fix["flag_story"], fix["attempt"], fix["origin_parent"]), (fixed, 12, 2, first))

    def test_after_the_last_attempt_the_failed_child_is_left_for_a_person_and_nothing_is_filed(self):
        self.gh.issues[12]["body"] = child_tickets.render_marker({**MARKER, "fix_attempt": 2}) + "\n\n" + FORM
        before = len(self.gh.issues)
        got = self.file(max_attempts=2)
        self.assertEqual(got["action"], "needs_human")
        self.assertEqual(len(self.gh.issues), before)
        self.assertIn("needs-human", self.labels(12))
        self.assertNotIn("waiting-on-plan", self.labels(12))

    def test_a_flag_that_is_still_on_makes_a_regression_with_no_marker_and_a_fresh_flag(self):
        got = self.file(verdict(released=True))
        body = self.gh.issues[got["number"]]["body"]
        self.assertEqual(child_tickets.read_fix_for(body), {})
        self.assertIn("update-app-intake", self.labels(got["number"]))  # planned straight away
        self.assertEqual(self.gh.blocked, {})  # nothing is blocked: the story is closed work
        self.assertTrue(any(f"#{got['number']}" in c for c in self.gh.comments[12]))

    def test_an_event_with_no_story_or_an_issue_that_is_not_a_planned_child_is_a_plain_bug_intake(self):
        none = self.file(verdict(story=None, source="production_feedback", severity="failure", fp="prod"))
        self.assertEqual(none["action"], "bug_intake")
        self.assertEqual(child_tickets.read_fix_for(self.gh.issues[none["number"]]["body"]), {})
        self.gh.issues[12]["body"] = FORM
        plain = self.file(verdict(fp="plain"))
        self.assertEqual(child_tickets.read_fix_for(self.gh.issues[plain["number"]]["body"]), {})
        self.assertEqual(self.gh.blocked, {})

    def test_a_refusal_to_block_takes_the_bug_back_and_holds_the_failed_child(self):
        self.gh.fail = {"dependencies/blocked_by": 422}
        got = self.file()
        self.assertEqual(got["action"], "needs_human")
        self.assertTrue(any(isinstance(c, list) and c[:2] == ["issue", "close"] for c in self.gh.calls))
        self.assertIn("needs-human", self.labels(12))
        self.assertNotIn("update-app-intake", self.labels(next(n for n in self.gh.issues if n > 12 and self.gh.issues[n].get("title", "").startswith("demo:"))))  # planning never started

    def test_a_factory_cause_files_a_fix_request_for_the_child_and_holds_it_until_the_fix_merges(self):
        got = self.file(verdict(target="factory"))
        self.assertEqual(got["action"], "fix_request")
        body = self.gh.issues[got["number"]]["body"]
        self.assertIn("<!-- failed-child:12 -->", body)
        self.assertEqual({"fix-request", "factory-fix-request"}, self.labels(got["number"]))
        self.assertIn("needs-human", self.labels(12))
        self.assertTrue(any("starts again by itself when the fix is merged" in c for c in self.gh.comments[12]))

    def test_no_cause_is_an_information_request_and_a_warning_does_not_hold_a_child(self):
        info = self.file(verdict(target="info"))
        self.assertEqual(self.labels(info["number"]), {"fix-request"})
        self.assertIn("needs-human", self.labels(12))
        self.gh.issues[12]["labels"] = []
        self.file(verdict(target="factory", severity="warning", fp="w"))
        self.assertNotIn("needs-human", self.labels(12))


if __name__ == "__main__":
    unittest.main()
