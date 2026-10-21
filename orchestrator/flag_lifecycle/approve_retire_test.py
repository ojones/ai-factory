import json
import unittest
from unittest import mock

from shared import github, shell

from flag_lifecycle import approve_retire


class Approval(unittest.TestCase):
    LABELS = ["update-app-intake", "app:notes", "flag:pin-notes", "dark-broken", "needs-human"]

    def test_approving_files_and_starts_the_removal_and_closes_the_story(self):
        calls = []

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            calls.append(cmd)
            if cmd[:3] == ["gh", "issue", "view"]:
                return mock.Mock(stdout=json.dumps({"title": "t", "labels": [{"name": l} for l in self.LABELS + ["approve-retire"]]}))
            return mock.Mock(stdout="")

        def fake_gh(args, token, check=False):
            calls.append(["gh", *args])
            return mock.Mock(stdout="https://github.com/o/f/issues/90" if args[:2] == ["issue", "create"] else "")
        with mock.patch.object(shell, "sh", fake_sh), mock.patch.object(github, "run", fake_gh), mock.patch.object(github, "ensure_label"):
            self.assertEqual(approve_retire.approve("o/f", "pat", 12), 0)
        create = next(c for c in calls if c[:3] == ["gh", "issue", "create"])
        self.assertIn("### App name\n\nnotes", create[create.index("--body") + 1])
        self.assertFalse(any(c[:3] == ["gh", "issue", "edit"] and c[3] == "90" for c in calls), msg="planned like any Update App Intake: the label at creation starts planning")
        self.assertTrue(any(c[:3] == ["gh", "issue", "close"] and c[3] == "12" for c in calls))

    def test_a_refused_approval_says_why_and_starts_nothing(self):
        calls = []

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            calls.append(cmd)
            if cmd[:3] == ["gh", "issue", "view"]:
                return mock.Mock(stdout=json.dumps({"title": "t", "labels": [{"name": "update-app-intake"}, {"name": "approve-retire"}]}))
            return mock.Mock(stdout="")
        with mock.patch.object(shell, "sh", fake_sh):
            approve_retire.approve("o/f", "pat", 12)
        self.assertFalse(any(c[:3] == ["gh", "issue", "create"] for c in calls))
        comment = next(c for c in calls if c[:3] == ["gh", "issue", "comment"])
        self.assertIn("Retirement not started", comment[comment.index("--body") + 1])

if __name__ == "__main__":
    unittest.main()
