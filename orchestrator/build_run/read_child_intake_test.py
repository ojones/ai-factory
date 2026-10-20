import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from planning import render_child  # noqa: E402
from shared import run_stops  # noqa: E402

from build_run import read_child  # noqa: E402

FORM = "### App name\n\n{app}\n\n### What should change?\n\n{task}\n\n### Cost cap override (USD)\n\n{cap}\n"


class Form(unittest.TestCase):
    def test_a_task_both_parsers_agree_on(self):
        body = FORM.format(app="a", task="Add search\nby title", cap="$3")
        self.assertEqual(read_child.parse_intake(body, 2.0, 10.0), ("Add search\nby title", 3.0))
        self.assertEqual(read_child.parse_intake("### What should be built?\n\nA thing\n", 2.0, 10.0), ("A thing", 2.0))
        with self.assertRaises(run_stops.NeedsHuman):
            read_child.parse_intake(FORM.format(app="a", task="_No response_", cap=""), 2.0, 10.0)


class Identity(unittest.TestCase):
    def issue(self, title="notes", labels=(), body=""):
        return {"title": title, "body": body, "labels": [{"name": n} for n in labels]}

    def test_a_new_app_intake_is_titled_with_the_app(self):
        self.assertEqual(read_child.identify_intake(self.issue(labels=["new-app-intake"]), "notes", 5), (False, {}))
        with self.assertRaises(run_stops.NeedsHuman):
            read_child.identify_intake(self.issue(title="other"), "notes", 5)

    def test_an_update_intake_needs_the_form_the_label_and_the_matching_app(self):
        body = FORM.format(app="notes", task="x", cap="")
        ok = self.issue(title="notes: add tags", labels=["update-app-intake", "app:notes"], body=body)
        self.assertEqual(read_child.identify_intake(ok, "notes", 5), (True, {}))
        for bad in (self.issue(labels=["update-app-intake"], body=body),  # no app: label
                    self.issue(labels=["update-app-intake", "app:todo"], body=body),
                    self.issue(labels=["update-app-intake", "app:todo"], body=FORM.format(app="todo", task="x", cap="")),
                    self.issue(labels=["update-app-intake", "app:notes"], body="no form")):
            with self.assertRaises(run_stops.NeedsHuman):
                read_child.identify_intake(bad, "notes", 5)

    def test_a_child_issue_reports_its_plan_metadata(self):
        body = render_child.child_body("notes", "t", 7, {"id": "CS-2"})
        _, meta = read_child.identify_intake(self.issue(labels=["update-app-intake", "app:notes"], body=body), "notes", 5)
        self.assertEqual(meta["parent"], 7)


if __name__ == "__main__":
    unittest.main()
