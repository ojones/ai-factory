import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from request import read_form  # noqa: E402
from shared import child_tickets  # noqa: E402

from planning import plan_comment, render_child  # noqa: E402


def proc(stdout="", returncode=0):
    return mock.Mock(stdout=stdout, returncode=returncode, stderr="")


class ChangeSets(unittest.TestCase):
    CS = {"id": "CS-2", "title": "Filter by species", "criteria": ["AC-1: ?species= filters"], "verification": ["curl with the filter"],
          "out_of_scope": ["sorting"], "flag": "species-filter"}

    def test_the_task_carries_criteria_checks_scope_and_the_flag(self):
        text = render_child.render_change_set_task(self.CS, request="Record sightings and filter them", parent=7)
        for needle in ("Change set CS-2: Filter by species", "Do only this change set", "Record sightings and filter them", "- AC-1: ?species= filters",
                       "- curl with the filter", "- sorting", "slug `species-filter`"):
            self.assertIn(needle, text)

    def test_a_flagged_change_set_leaves_the_slug_for_the_run_to_fill_in_and_the_comment_says_so(self):
        cs = dict(self.CS, flag=True)
        self.assertIn("slug `" + child_tickets.FLAG_SLOT + "`", render_child.render_change_set_task(cs))
        self.assertIn("a flag named for its issue", plan_comment.render_plan_comment({"change_sets": [dict(cs, id="CS-1", title="t")]}))
        self.assertIn("slug `species-filter`", render_child.render_change_set_task(self.CS))  # an older plan's own slug is kept

    def test_an_internal_change_says_it_needs_no_flag(self):
        text = render_child.render_change_set_task(dict(self.CS, flag=None, out_of_scope=[]))
        self.assertIn("needs no flag", text)
        self.assertNotIn("Out of scope", text)
        self.assertNotIn("original request", text)

    def test_child_metadata_round_trips_and_other_issues_have_none(self):
        body = render_child.child_body("notes", "do it", 7, {"id": "CS-2"})
        marker = child_tickets.read_marker(body)
        self.assertEqual((marker["parent"], marker["cs"], marker["kind"]), (7, "CS-2", "update"))
        staging = render_child.child_body("notes", "do it", 7, {"id": "CS-1", "flag": None, "size": "M"}, kind="staging")
        self.assertEqual((child_tickets.read_marker(staging)["kind"], child_tickets.read_marker(staging)["flag"]), ("staging", False))
        self.assertEqual(read_form.app_name(body), "notes")
        for none in ("", None, "no marker", "<!-- factory-plan:{broken -->", "<!-- factory-plan:[1] -->"):
            self.assertEqual(child_tickets.read_marker(none), {})

    def test_a_fix_childs_marker_names_the_child_it_fixes_and_which_attempt_it_is_and_no_flag_to_reuse(self):
        marker = child_tickets.read_marker(render_child.child_body("notes", "do it", 7, {"id": "CS-1", "flag": True}, fix_for=12, fix_attempt=2))
        self.assertEqual((marker["fix_for"], marker["fix_attempt"], marker["flag"]), (12, 2, True))
        self.assertNotIn("flag_story", marker)
        plain = child_tickets.read_marker(render_child.child_body("notes", "do it", 7, {"id": "CS-1"}))
        self.assertNotIn("fix_for", plain)

    def test_children_keep_the_parents_cost_cap(self):
        self.assertIn("### Cost cap override (USD)\n\n1.00", render_child.child_body("notes", "t", 7, {"id": "CS-1"}, "1.00"))
        self.assertIn("### Cost cap override (USD)\n\n_No response_", render_child.child_body("notes", "t", 7, {"id": "CS-1"}))

    def test_the_plan_comment_shows_change_sets_assumptions_and_questions(self):
        plan = {"change_sets": [{"id": "CS-1", "title": "Soft-delete a todo", "flag": "delete-todo"},
                                {"id": "CS-2", "title": "Cleanup", "flag": None}],
                "assumptions": ["Deleting is a soft delete, so records are kept"]}
        text = plan_comment.render_plan_comment(plan, ["Should deleted todos be recoverable?"])
        for needle in ("Plan: 2 change sets", "**CS-1** Soft-delete a todo (flag `delete-todo`)", "no flag (internal)",
                       "Assumptions I made for you", "soft delete, so records are kept", "I need an answer", "recoverable?"):
            self.assertIn(needle, text)
        one = plan_comment.render_plan_comment({"change_sets": [{"id": "CS-1", "title": "x", "flag": "f"}]})
        self.assertIn("Plan: 1 change set.", one)
        self.assertNotIn("Assumptions", one)
        self.assertNotIn("answer", one)

    def test_titles_are_one_short_line(self):
        self.assertEqual(render_child.one_line("a\n  b\tc"), "a b c")
        self.assertEqual(len(render_child.one_line("x" * 500)), 80)


if __name__ == "__main__":
    unittest.main()
