import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import close_child  # noqa: E402
from shared import child_tickets, github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402
from try_fix import resume_after_merge  # noqa: E402

from factory_change import open_pr, pause, watch_merged  # noqa: E402

MERGED_AT = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
NOW_SOON, NOW_LATER = MERGED_AT + timedelta(hours=2), MERGED_AT + timedelta(hours=25)


class Gh(FakeIssues):
    def __init__(self):
        super().__init__()
        self.prs, self.drift, self.seen_again = [], [], False

    def __call__(self, args, token, check=False):
        if args[:2] == ["pr", "list"]:
            return self.ok(self.prs)
        if args[:2] == ["pr", "edit"]:
            self.calls.append(args)
            return self.empty()
        if args[:2] == ["issue", "list"] and "model-drift" in args:
            return self.ok(self.drift)
        return super().__call__(args, token, check)


class Watching(unittest.TestCase):
    def setUp(self):
        self.gh = Gh()
        self.intake, self.child = self.gh.add(3), self.gh.add(5)
        self.gh.prs = [{"number": 9, "mergedAt": "2026-10-21T12:00:00Z", "body": open_pr.pr_body(5, "s", "a.b.C.d", "tier_one", ["x"])}]
        self.advance, self.resume = mock.Mock(), mock.Mock()
        for obj, name, value in ((github, "run", self.gh), (github, "ensure_label", mock.Mock()), (child_tickets, "parent_of", lambda *a, **k: 3),
                                 (close_child, "advance", self.advance), (resume_after_merge, "resume", self.resume)):
            patcher = mock.patch.object(obj, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sweep(self, now):
        return watch_merged.sweep("o/f", "pat", now, 24)

    def test_a_quiet_window_closes_the_child_advances_the_plan_and_resumes_the_failed_child(self):
        self.assertEqual(self.sweep(NOW_LATER), {9: "merged"})
        self.assertEqual(self.gh.issues[self.child]["state"], "open", "the fake does not close issues; the call is what matters")
        self.assertIn(["issue", "close", "5", "--repo", "o/f", "--reason", "completed"], self.gh.calls)
        self.advance.assert_called_once_with("o/f", "pat", 5)
        self.resume.assert_called_once()

    def test_a_change_still_inside_its_window_is_left_watching(self):
        self.assertEqual(self.sweep(NOW_SOON), {9: None})
        self.advance.assert_not_called()

    def test_the_finding_coming_back_pauses_and_reverts_nothing(self):
        self.gh.comments[3] = []
        self.gh.cli_view = lambda args: self.gh.ok({"labels": [], "body": "", "comments": [{"body": "**Seen again:** x", "createdAt": "2026-10-21T13:00:00Z"}]})
        self.assertEqual(self.sweep(NOW_SOON), {9: "paused"})
        self.assertFalse([c for c in self.gh.calls if "revert" in " ".join(c).lower()])
        self.assertTrue(pause.is_paused("o/f", "pat"))
        self.advance.assert_not_called()

    def test_a_model_drift_alert_after_the_merge_pauses_and_reverts_nothing(self):
        self.gh.drift = [{"number": 40, "createdAt": "2026-10-21T14:00:00Z"}]
        self.assertEqual(self.sweep(NOW_SOON), {9: "paused"})
        self.assertFalse([c for c in self.gh.calls if "revert" in " ".join(c).lower()])

    def test_an_alert_from_before_the_merge_does_not_count(self):
        self.gh.drift = [{"number": 40, "createdAt": "2026-10-20T14:00:00Z"}]
        self.assertEqual(self.sweep(NOW_SOON), {9: None})

    def test_a_merge_is_announced_on_the_child(self):
        outcome = watch_merged.start_watching("o/f", "pat", 9, self.gh.prs[0]["body"])
        self.assertEqual(outcome, "merged")
        self.assertIn("watched", self.gh.comments[5][0])


if __name__ == "__main__":
    unittest.main()
