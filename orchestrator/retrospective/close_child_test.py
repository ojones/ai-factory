import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from request import intake_labels  # noqa: E402
from shared import child_tickets  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from retrospective import close_child  # noqa: E402

W, S = child_tickets.WAIT, intake_labels.START


def kid(n, state, labels=()):
    return {"number": n, "state": state, "labels": set(labels)}


def blockers(table):
    return lambda n: [{"number": k, "state": v} for k, v in table.get(n, {}).items()]


class ReadyToStart(unittest.TestCase):
    def test_a_child_starts_when_every_blocker_is_closed(self):
        kids = [kid(1, "OPEN"), kid(2, "OPEN", [W]), kid(3, "OPEN", [W])]
        self.assertEqual(close_child.ready_to_start(kids, blockers({2: {1: "OPEN"}, 3: {1: "OPEN", 2: "OPEN"}})), [])
        kids[0]["state"] = "CLOSED"
        self.assertEqual(close_child.ready_to_start(kids[:1] + kids[1:], blockers({2: {1: "CLOSED"}, 3: {1: "CLOSED", 2: "OPEN"}})), [2])

    def test_only_one_child_starts_at_a_time_the_lowest_number_first(self):
        kids = [kid(3, "OPEN", [W]), kid(2, "OPEN", [W])]
        self.assertEqual(close_child.ready_to_start(kids, blockers({})), [2])

    def test_nothing_starts_while_another_child_is_in_flight(self):
        kids = [kid(1, "OPEN", [S]), kid(2, "OPEN", [W])]
        self.assertEqual(close_child.ready_to_start(kids, blockers({})), [])
        kids[0]["state"] = "CLOSED"
        self.assertEqual(close_child.ready_to_start(kids, blockers({})), [2])

    def test_a_stalled_child_blocks_its_siblings_until_it_is_retried_or_closed(self):
        # it lost `proceed-with-change` when its run stopped, and it is not waiting any more: nothing else may start behind it
        kids = [kid(1, "OPEN"), kid(2, "OPEN", [W]), kid(3, "OPEN", [W])]
        self.assertEqual(close_child.ready_to_start(kids, blockers({})), [])
        kids[0]["labels"] = {S}  # retried: in flight again
        self.assertEqual(close_child.ready_to_start(kids, blockers({})), [])
        kids[0]["state"] = "CLOSED"
        self.assertEqual(close_child.ready_to_start(kids, blockers({})), [2])

    def test_a_closed_child_is_never_started_again(self):
        self.assertEqual(close_child.ready_to_start([kid(1, "CLOSED", [W])], blockers({})), [])

    def test_a_blocker_on_a_child_outside_the_list_is_judged_by_its_own_state(self):
        self.assertEqual(close_child.ready_to_start([kid(2, "OPEN", [W])], blockers({2: {99: "OPEN"}})), [])


class Advance(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        self.parent = self.gh.add(7)
        self.tickets = child_tickets.ChildTickets("o/f", 7, "pat", self.gh)
        self.a = self.tickets.file("a", "", ["update-app-intake", W])
        self.b = self.tickets.file("b", "", ["update-app-intake", W])
        self.c = self.tickets.file("c", "", ["update-app-intake", W])
        self.tickets.block(self.b, self.a)
        self.tickets.block(self.c, self.b)

    def advance(self, number):
        with mock.patch.object(close_child, "sh") as sh:
            result = close_child.advance("o/f", "pat", number, self.tickets)
        return result, [c.args[0] for c in sh.call_args_list]

    def close(self, n):
        self.gh.issues[n]["state"] = "closed"

    def test_the_next_child_starts_when_the_one_it_waited_on_closes(self):
        self.gh.issues[self.a]["labels"] = [{"name": S}]
        self.close(self.a)
        result, edits = self.advance(self.a)
        self.assertEqual(result, {"started": [self.b], "parent_closed": False})
        self.assertEqual(edits[0][:3], ["gh", "issue", "edit"])
        self.assertIn(str(self.b), edits[0])
        self.assertIn(S, edits[0])
        self.assertIn(W, edits[0])

    def test_a_child_whose_blocker_is_still_open_does_not_start(self):
        self.close(self.a)
        self.gh.issues[self.b]["state"] = "open"
        self.gh.blocked[self.b] = [self.a, self.c]  # also blocked by a later, still open child
        self.assertEqual(self.advance(self.a)[0]["started"], [])

    def test_the_parent_closes_only_when_the_last_child_closes(self):
        for n in (self.a, self.b):
            self.close(n)
        result, _ = self.advance(self.b)
        self.assertFalse(result["parent_closed"])
        self.assertEqual(self.gh.issues[self.parent]["state"], "open")
        self.close(self.c)
        result, edits = self.advance(self.c)
        self.assertEqual(result, {"started": [], "parent_closed": True})
        self.assertEqual(self.gh.issues[self.parent]["state"], "closed")
        self.assertEqual(edits, [])  # nothing is started once everything is done

    def test_a_failed_child_blocks_the_ones_after_it(self):
        # b was started and its run stopped: it lost the go label, so c may not start even though a is closed
        self.close(self.a)
        self.gh.issues[self.b]["labels"] = []
        self.assertEqual(self.advance(self.a)[0]["started"], [])

    def test_an_issue_with_no_parent_does_nothing(self):
        with mock.patch.object(close_child.child_tickets, "parent_of", return_value=None):
            self.assertEqual(close_child.advance("o/f", "pat", 5), {"started": [], "parent_closed": False})


class Finishing(unittest.TestCase):
    def test_a_finished_update_intake_is_closed_and_releases_what_waits(self):
        with mock.patch.object(close_child, "sh") as sh, mock.patch.object(close_child, "advance") as advance:
            close_child.finish_update_intake(True, "o/f", "9", "pat")
        self.assertEqual(sh.call_args[0][0][:3], ["gh", "issue", "close"])
        advance.assert_called_once_with("o/f", "pat", "9")

    def test_a_stopped_one_loses_the_go_label_so_it_can_be_retried(self):
        with mock.patch.object(close_child, "sh") as sh, mock.patch.object(close_child, "advance") as advance:
            close_child.finish_update_intake(False, "o/f", "9", "pat")
        cmd = sh.call_args[0][0]
        self.assertEqual(cmd[:3], ["gh", "issue", "edit"])
        self.assertIn("--remove-label", cmd)
        self.assertIn(S, cmd)
        advance.assert_not_called()

    def test_a_failure_while_finishing_never_raises(self):
        with mock.patch.object(close_child, "sh", side_effect=OSError("no gh")):
            close_child.finish_update_intake(True, "o/f", "9", "pat")


class SettleFix(unittest.TestCase):
    # Plan 5 has the failed child 12 (waiting, blocked by the bug Intake 50) and a sibling 13; the bug Intake 50 has its one fix child 51.
    def setUp(self):
        self.gh = FakeIssues()
        self.gh.add(5)
        self.gh.add(12, labels=["update-app-intake", W])
        self.gh.add(13, labels=["update-app-intake", W])
        self.gh.subs[5] = [12, 13]
        self.gh.add(50, body=child_tickets.render_fix_for(12, 12, 5, True, 1) + "\n\n### App name\n\ndemo\n")
        self.gh.add(51, labels=["update-app-intake", S])
        self.gh.subs[50] = [51]
        self.gh.blocked[12] = [50]
        self.gh.blocked[13] = [12]

    def close_fix(self):
        self.gh.issues[51]["state"] = "closed"
        with mock.patch.object(close_child, "sh") as sh, mock.patch.object(close_child.github, "run", self.gh):
            result = close_child.advance("o/f", "pat", 51, child_tickets.ChildTickets("o/f", 50, "pat", self.gh))
        return result, [c.args[0] for c in sh.call_args_list]

    def test_when_the_bug_intake_closes_the_story_hears_it_and_the_failed_child_starts_again_not_its_sibling(self):
        result, edits = self.close_fix()
        self.assertTrue(result["parent_closed"])  # the fix child was the Intake's last child
        self.assertEqual(self.gh.issues[50]["state"], "closed")
        self.assertEqual(result["started"], [12])
        self.assertTrue(any("The fix for this change set is done" in c for c in self.gh.comments[12]))
        self.assertEqual([e[3] for e in edits], ["12"])  # only the failed child starts, never the sibling behind it

    def test_a_plan_that_is_not_a_bug_intake_settles_nothing(self):
        self.assertEqual(close_child.settle_fix("o/f", "pat", 5, self.gh), [])
        self.assertNotIn(12, self.gh.comments)

    def test_the_failed_child_waits_while_its_bug_intake_is_open(self):
        self.gh.issues[50]["state"] = "open"
        with mock.patch.object(close_child, "sh") as sh:
            result = close_child.advance_plan("o/f", "pat", 5, child_tickets.ChildTickets("o/f", 5, "pat", self.gh))
        self.assertEqual(result["started"], [])
        sh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
