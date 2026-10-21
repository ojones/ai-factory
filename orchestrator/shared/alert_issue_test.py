import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import alert_issue  # noqa: E402


class SyncAlertIssue(unittest.TestCase):
    def sync(self, found, open_issues):
        calls = []

        def sh(cmd, env=None, check=True):
            calls.append(cmd)
            return mock.Mock(stdout=open_issues)
        with mock.patch.object(alert_issue.shell, "sh", sh):
            alert_issue.sync_alert_issue("o/f", "t", "lbl", found, "b", "Title", "all clear", extra_labels=("needs-human",))
        return [c for c in calls if c[1:3] != ["issue", "list"]]

    def test_nothing_found_and_one_open_closes_it(self):
        acted = self.sync([], '[{"number": 4, "body": "old"}]')
        self.assertEqual([c[1:3] for c in acted], [["issue", "close"]])

    def test_found_with_none_open_creates_one_with_every_label(self):
        acted = self.sync(["x"], "[]")
        self.assertEqual([c[1:3] for c in acted], [["issue", "create"]])
        self.assertEqual(acted[0].count("--label"), 2)

    def test_found_with_the_same_body_open_changes_nothing(self):
        self.assertEqual(self.sync(["x"], '[{"number": 4, "body": "b"}]'), [])

    def test_found_with_a_different_body_edits_it(self):
        acted = self.sync(["x"], '[{"number": 4, "body": "old"}]')
        self.assertEqual([c[1:3] for c in acted], [["issue", "edit"]])


if __name__ == "__main__":
    unittest.main()
