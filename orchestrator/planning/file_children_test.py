import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from request import intake_labels  # noqa: E402
from shared import child_tickets, github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from planning import file_children  # noqa: E402


def sets():
    base = {"criteria": ["a"], "verification": ["b"], "size": "S", "requirements": ["REQ-1"], "internal_only": False}
    return [dict(base, id="CS-1", title="Save", flag=True, depends_on=[]),
            dict(base, id="CS-2", title="Filter", flag=True, depends_on=["CS-1"]),
            dict(base, id="CS-3", title="Export", flag=None, internal_only=True, depends_on=[])]


class FilingChildren(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        self.gh.add(7)
        self.tickets = child_tickets.ChildTickets("o/f", 7, "pat", self.gh)

    def file(self, **kw):
        with mock.patch.object(github, "run", self.gh):
            return file_children.file_children("o/f", "pat", "notes", 7, sets(), ["CS-1", "CS-2", "CS-3"], "the request", tickets=self.tickets, **kw)

    def test_children_are_sub_issues_with_complete_bodies_dependencies_as_blockers_and_only_the_first_root_starts(self):
        made = self.file()
        self.assertEqual([cs for cs, _ in made], ["CS-1", "CS-2", "CS-3"])
        numbers = dict(made)
        self.assertEqual(self.gh.subs[7], [numbers["CS-1"], numbers["CS-2"], numbers["CS-3"]])
        self.assertEqual(self.gh.blocked, {numbers["CS-2"]: [numbers["CS-1"]]})
        second = self.gh.issues[numbers["CS-2"]]
        marker = child_tickets.read_marker(second["body"])
        self.assertEqual((marker["parent"], marker["cs"], marker["kind"], marker["flag"], marker["size"]),
                         (7, "CS-2", "update", True, "S"))
        self.assertIn("- AC-1" if False else "- a", second["body"], msg="the criteria are in the body: the child needs nothing else to be built")
        self.assertIn("### What should change?", second["body"])
        self.assertEqual({label["name"] for label in second["labels"]}, {"update-app-intake", "app:notes", "waiting-on-plan"}, msg="the parent link is the sub-issue, not a label")
        starts = [c for c in self.gh.calls if isinstance(c, list) and c[:2] == ["issue", "edit"]]
        self.assertEqual([c[2] for c in starts], [str(numbers["CS-1"])], msg="CS-3 has nothing to wait for either, but waits its turn")
        self.assertIn(intake_labels.START, starts[0])

    def test_a_fix_child_is_an_ordinary_child_that_keeps_the_planners_flag_decision_and_records_what_it_fixes(self):
        one = [dict(sets()[0], flag=None, internal_only=True)]
        flagged = [dict(sets()[0], flag=True)]
        for plan, expected_flag in ((one, False), (flagged, True)):
            gh = FakeIssues()
            gh.add(7)
            with mock.patch.object(github, "run", gh):
                made = file_children.file_children("o/f", "pat", "notes", 7, plan, ["CS-1"], "req", tickets=child_tickets.ChildTickets("o/f", 7, "pat", gh),
                                                   fix={"fix_for": 12, "origin_parent": 5, "attempt": 2})
            marker = child_tickets.read_marker(gh.issues[made[0][1]]["body"])
            self.assertEqual((marker["flag"], marker["fix_for"], marker["fix_attempt"]), (expected_flag, 12, 2))
            self.assertEqual(set(marker) & {"flag_story", "origin_parent"}, set())
            body = gh.issues[made[0][1]]["body"]
            self.assertEqual("slug `" in body, expected_flag)

    def test_an_ordinary_child_has_no_fix_markers(self):
        made = self.file()
        marker = child_tickets.read_marker(self.gh.issues[made[0][1]]["body"])
        self.assertEqual(set(marker) & {"fix_for", "fix_attempt", "flag_story"}, set())

    def test_a_parent_that_already_has_children_is_not_planned_twice(self):
        first = self.file()
        again = self.file()
        self.assertEqual(again, first)
        self.assertEqual(len(self.gh.subs[7]), 3)

    def test_a_failure_part_way_takes_back_what_was_made_and_raises_so_the_intake_can_be_planned_again(self):
        original, count = self.gh.route, {"n": 0}

        def second_link_fails(method, path, fields):
            if method == "POST" and path.endswith("sub_issues"):
                count["n"] += 1
                if count["n"] == 2:
                    return mock.Mock(stdout="", stderr="HTTP 422", returncode=1)
            return original(method, path, fields)

        self.gh.route = second_link_fails
        with self.assertRaises(child_tickets.ChildTicketError):
            self.file()
        self.assertEqual([i["state"] for n, i in self.gh.issues.items() if n != 7], ["closed", "closed"], msg="the filed one and the unlinked one")
        self.assertEqual(self.gh.subs[7], [], msg="neither is left under the parent, so the Intake does not count as planned")
        self.gh.route = original
        self.assertEqual(len(self.file()), 3)

    def test_a_blocker_failure_also_leaves_nothing_open(self):
        self.gh.fail = {"dependencies/blocked_by": 422}
        with self.assertRaises(child_tickets.ChildTicketError):
            self.file()
        self.assertTrue(all(i["state"] == "closed" for n, i in self.gh.issues.items() if n != 7))
        self.assertEqual(self.gh.subs[7], [])


if __name__ == "__main__":
    unittest.main()
