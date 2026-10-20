import unittest
from unittest import mock

from shared import github

from request import file_intake, read_form


class Recorder:
    def __init__(self, created="https://github.com/o/f/issues/90"):
        self.calls, self.created, self.labels = [], created, []

    def run(self, args, token, check=False):
        self.calls.append((args, token, check))
        return mock.Mock(stdout=self.created if args[:2] == ["issue", "create"] else "")

    def ensure_label(self, repo, name, token, color="", description=""):
        self.labels.append((name, token))

    def file(self, **kw):
        with mock.patch.object(github, "run", self.run), mock.patch.object(github, "ensure_label", self.ensure_label):
            return file_intake.file_update_app_intake("o/f", "actions-token", "the-pat", "notes", "notes: do it", "Add tags", **kw)


class FileUpdateAppIntake(unittest.TestCase):
    def test_it_files_a_form_shaped_intake_labelled_for_the_app_and_its_source(self):
        r = Recorder()
        self.assertEqual(r.file(source_label="production-feedback", source_label_desc="d", started_note="Started."), 90)
        create = next(c for c in r.calls if c[0][:2] == ["issue", "create"])
        args = create[0]
        self.assertEqual(args[args.index("--label") + 1], "update-app-intake,app:notes,production-feedback")
        body = args[args.index("--body") + 1]
        self.assertEqual((read_form.app_name(body), read_form.read_request(body, 2.0, 10.0)[0]), ("notes", "Add tags"))
        self.assertEqual(create[1], "the-pat")  # created by the PAT user, so its label event starts planning

    def test_planning_is_started_by_the_label_at_creation_not_by_a_start_label(self):
        r = Recorder()
        r.file()
        self.assertFalse(any(c[0][:2] == ["issue", "edit"] for c in r.calls))
        self.assertNotIn("proceed-with-change", [n for n, _ in r.labels])

    def test_the_labels_are_made_first_and_a_note_is_posted_only_when_given(self):
        r = Recorder()
        r.file(source_label="maintenance", started_note="Started.")
        self.assertEqual([n for n, _ in r.labels], ["update-app-intake", "app:notes", "maintenance"])
        self.assertTrue(any(c[0][:2] == ["issue", "comment"] and c[0][-1] == "Started." for c in r.calls))
        quiet = Recorder()
        quiet.file()
        self.assertFalse(any(c[0][:2] == ["issue", "comment"] for c in quiet.calls))
        self.assertNotIn("maintenance", [n for n, _ in quiet.labels])

    def test_when_github_returns_no_issue_number_nothing_is_returned(self):
        self.assertIsNone(Recorder(created="").file())

    def test_check_makes_a_failed_call_raise(self):
        r = Recorder()
        r.file(check=True)
        self.assertTrue(all(c[2] for c in r.calls if c[0][:2] == ["issue", "create"]))


if __name__ == "__main__":
    unittest.main()
