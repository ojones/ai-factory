import unittest

from shared import child_tickets as ct
from shared.fake_issues import FakeIssues

CS = {"id": "CS-2", "title": "t", "flag": True, "internal_only": False, "size": "S", "requirements": ["REQ-1"]}


class Marker(unittest.TestCase):
    def test_a_marker_round_trips_through_a_body_and_other_issues_have_none(self):
        meta = ct.marker_for(CS, 7, "update", [{"name": "A_KEY", "purpose": "x", "read_by": "backend"}])
        self.assertEqual(meta, {"parent": 7, "cs": "CS-2", "kind": "update", "flag": True, "internal_only": False, "size": "S", "requirements": ["REQ-1"],
                                "secrets": [{"name": "A_KEY", "purpose": "x"}]})
        self.assertEqual(ct.read_marker("text\n" + ct.render_marker(meta) + "\nmore"), meta)
        for none in ("", None, "no marker", "<!-- factory-plan:{broken -->", "<!-- factory-plan:[1] -->"):
            self.assertEqual(ct.read_marker(none), {})

    def test_a_flag_is_a_yes_or_no_in_the_marker_and_the_slug_is_never_in_it(self):
        self.assertFalse(ct.marker_for(dict(CS, flag=None), 7)["flag"])
        self.assertFalse(hasattr(ct, "story_number"))


class Children(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        self.parent = self.gh.add(7)
        self.tickets = ct.ChildTickets("o/f", 7, "pat", self.gh)

    def test_a_child_is_created_then_added_under_its_parent_by_its_numeric_id(self):
        n = self.tickets.file("t", ct.render_marker({"cs": "CS-1"}) + "\nbody", ["a", "b"])
        self.assertEqual(self.gh.subs[7], [n])
        created, linked = self.gh.calls[0], self.gh.calls[1]
        self.assertEqual(created[:2], ("POST", "issues"))
        self.assertEqual(created[2]["labels[]"], ["a", "b"])
        self.assertEqual(linked[:2], ("POST", "issues/7/sub_issues"))
        self.assertEqual(linked[2]["sub_issue_id"], [str(self.gh.issues[n]["id"])])
        listed = self.tickets.children()
        self.assertEqual([(c["number"], c["state"], c["marker"]) for c in listed], [(n, "OPEN", {"cs": "CS-1"})])
        self.assertEqual(listed[0]["labels"], {"a", "b"})

    def test_a_child_that_cannot_be_added_under_its_parent_is_closed_and_the_failure_is_loud(self):
        self.gh.fail = {"POST issues/7/sub_issues": 422}
        with self.assertRaises(ct.ChildTicketError) as cm:
            self.tickets.file("t", "b", [])
        self.assertIn("422", str(cm.exception))
        made = [i for n, i in self.gh.issues.items() if n != 7]
        self.assertEqual([i["state"] for i in made], ["closed"], msg="no open orphan")
        self.assertEqual(self.gh.subs, {})

    def test_a_failed_create_raises(self):
        self.gh.fail = {"POST issues": 500}
        with self.assertRaises(ct.ChildTicketError):
            self.tickets.file("t", "b", [])

    def test_readiness_is_judged_by_the_state_of_each_blocker_not_by_their_count(self):
        a, b = self.tickets.file("a", "", []), self.tickets.file("b", "", [])
        self.tickets.block(b, a)
        self.assertEqual(self.tickets.blockers(b), [{"number": a, "state": "OPEN"}])
        self.assertTrue(self.tickets.is_ready(a))
        self.assertFalse(self.tickets.is_ready(b))
        self.gh.issues[a]["state"] = "closed"
        self.assertTrue(self.tickets.is_ready(b), msg="closing the blocker does not remove it from the list; its state decides")
        self.gh.issues[b]["state"] = "closed"
        self.assertFalse(self.tickets.is_ready(b), msg="a closed child is not ready to start")

    def test_a_blocker_that_cannot_be_added_raises(self):
        a, b = self.tickets.file("a", "", []), self.tickets.file("b", "", [])
        self.gh.fail = {"dependencies/blocked_by": 422}
        with self.assertRaises(ct.ChildTicketError):
            self.tickets.block(b, a)

    def test_the_parent_of_a_child_is_found_and_no_parent_is_none_not_an_error(self):
        n = self.tickets.file("a", "", [])
        self.assertEqual(ct.parent_of("o/f", n, "pat", self.gh), 7)
        self.assertIsNone(ct.parent_of("o/f", 7, "pat", self.gh))
        self.gh.fail = {"/parent": 500}
        with self.assertRaises(ct.ChildTicketError):
            ct.parent_of("o/f", n, "pat", self.gh)


class FixFor(unittest.TestCase):
    def test_the_fix_for_marker_round_trips_and_any_other_body_has_none(self):
        marker = ct.render_fix_for(12, 5, 2)
        self.assertEqual(ct.read_fix_for(f"{marker}\n\n### App name\n\ndemo"),
                         {"fix_for": 12, "origin_parent": 5, "attempt": 2})
        for body in ("", None, "no marker", "<!-- fix-for:not json -->", '<!-- fix-for:{"x":1} -->', "<!-- fix-for:[1] -->"):
            self.assertEqual(ct.read_fix_for(body), {})

    def test_a_child_marker_records_which_fix_attempt_it_is_only_when_it_is_one(self):
        cs = {"id": "CS-1", "flag": True, "size": "S"}
        self.assertNotIn("fix_attempt", ct.marker_for(cs, 7))
        meta = ct.marker_for(cs, 7, "update", None, 12, 2)
        self.assertEqual((meta["fix_for"], meta["fix_attempt"]), (12, 2))


if __name__ == "__main__":
    unittest.main()
