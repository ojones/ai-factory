import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import child_tickets  # noqa: E402

from staging import read_staging_child as r  # noqa: E402

LIMITS = {"cost_cap_usd_default": 2.0, "cost_cap_usd_ceiling": 10.0}
PARENT_BODY = "### What should be built?\n\nA notes app\nwith tags\n\n### Cost cap override (USD)\n\n{cap}\n"


def child(kind="staging", parent=7, app="notes"):
    body = child_tickets.render_marker({"parent": parent, "cs": "CS-1", "kind": kind}) + f"\n\n### App name\n\n{app}\n\n### What should change?\n\nStage it\n"
    return {"number": 12, "body": body, "labels": []}


def check(c=None, parent=None, parent_body=None, in_flight=(), running=0, max_apps=1):
    return r.check_child(c or child(), {"number": 7, "state": "OPEN"} if parent is None else parent, {"body": parent_body or PARENT_BODY.format(cap="_No response_")},
                         list(in_flight), running, max_apps, LIMITS)


class Checking(unittest.TestCase):
    def test_a_staging_child_names_the_app_and_takes_the_request_and_cap_from_its_intake(self):
        got = check()
        self.assertEqual((got["app"], got["parent"], got["description"], got["cost_cap"], got["cap_source"]), ("notes", 7, "A notes app\nwith tags", "2.00", "default"))
        got = check(parent_body=PARENT_BODY.format(cap="$3"))
        self.assertEqual((got["cost_cap"], got["cap_source"]), ("3.00", "override"))

    def test_only_a_staging_child_of_an_open_intake_may_be_staged(self):
        for kwargs, why in ((dict(c=child(kind="update")), "not a staging child"), (dict(parent={"number": 9, "state": "OPEN"}), "names #7"),
                            (dict(parent={"number": 7, "state": "CLOSED"}), "is closed"), (dict(c=child(app="Bad Name")), "not a Managed App name"),
                            (dict(parent_body="### What should be built?\n\n_No response_\n"), "request field")):
            with self.assertRaises(r.NotStageable) as cm:
                check(**kwargs)
            self.assertIn(why, str(cm.exception))
        with self.assertRaises(r.NotStageable) as cm:
            r.check_child(child(), None, {"body": PARENT_BODY}, [], 0, 1, LIMITS)
        self.assertIn("not a sub-issue", str(cm.exception))

    def test_one_app_goes_through_staging_at_a_time_and_build_runs_count_too(self):
        with self.assertRaises(r.NotStageable) as cm:
            check(in_flight=[30])
        self.assertIn("#30", str(cm.exception))
        with self.assertRaises(r.NotStageable):
            check(running=1)
        self.assertEqual(check(running=1, max_apps=2)["app"], "notes")

    def test_only_other_staging_children_with_the_start_label_count_as_in_flight(self):
        stage = child_tickets.render_marker({"parent": 8, "cs": "CS-1", "kind": "staging"})
        update = child_tickets.render_marker({"parent": 8, "cs": "CS-2", "kind": "update"})
        issues = [{"number": 12, "body": stage}, {"number": 31, "body": stage}, {"number": 32, "body": update}, {"number": 33, "body": "no marker"}]
        self.assertEqual(r.staging_children_in_flight(issues, 12), [31])

    def test_the_shell_gets_quoted_values_so_a_request_cannot_inject_commands(self):
        found = {"app": "notes", "parent": 7, "description": "it's `rm -rf /` $(x)\nline two", "cost_cap": "2.00", "cap_source": "default"}
        lines = r.shell_lines(found)
        description = next(line.split("=", 1)[1] for line in lines if line.startswith("DESCRIPTION="))
        self.assertEqual(shlex.split(description), ["it's `rm -rf /` $(x)\nline two"])


if __name__ == "__main__":
    unittest.main()
