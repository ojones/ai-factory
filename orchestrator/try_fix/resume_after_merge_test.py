import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402

from try_fix import factory_fix_request, resume_after_merge  # noqa: E402


class Resume(unittest.TestCase):
    def go(self, body, state="OPEN", labels=("needs-human",)):
        calls = []

        def fake(args, token, check=False):
            calls.append((args, token))
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout=json.dumps({"state": state, "labels": [{"name": n} for n in labels]}))
            return mock.Mock(stdout="")

        with mock.patch.object(github, "run", fake):
            return resume_after_merge.resume("o/f", "the-pat", "tok", body), calls

    def test_a_merged_fix_starts_the_failed_child_again_with_the_pat(self):
        got, calls = self.go("Proposed.\n" + factory_fix_request.failed_child_marker(66))
        self.assertEqual(got, 66)
        start = next((a, t) for a, t in calls if a[:2] == ["issue", "edit"] and "proceed-with-change" in a)
        self.assertEqual((start[0][2], start[1]), ("66", "the-pat"), msg="events from the Actions token would not start the run")
        self.assertTrue(any(a[:2] == ["issue", "edit"] and "--remove-label" in a and "needs-human" in a for a, _ in calls))

    def test_a_pr_that_names_no_child_resumes_nothing(self):
        got, calls = self.go("A lesson, not a failure.")
        self.assertIsNone(got)
        self.assertEqual(calls, [])

    def test_a_child_that_is_closed_already_started_or_not_held_is_left_alone(self):
        marker = factory_fix_request.failed_child_marker(66)
        for kwargs in (dict(state="CLOSED"), dict(labels=("needs-human", "proceed-with-change")), dict(labels=())):
            got, calls = self.go(marker, **kwargs)
            self.assertIsNone(got, kwargs)
            self.assertFalse([a for a, _ in calls if a[:2] == ["issue", "edit"]], kwargs)

    def test_the_workflow_runs_only_for_a_merged_pr_that_names_a_child(self):
        root = Path(__file__).resolve().parent.parent.parent
        wf = yaml.safe_load((root / ".github/workflows/resume-failed-child.yml").read_text())
        self.assertEqual(wf[True]["pull_request"]["types"], ["closed"])
        cond = " ".join(next(iter(wf["jobs"].values()))["if"].split())
        self.assertIn("github.event.pull_request.merged == true", cond)
        self.assertIn("failed-child:", cond)
        merge = (root / ".github/workflows/factory-checks.yml").read_text()
        self.assertIn("GH_TOKEN: ${{ secrets.FACTORY_PAT }}", merge[merge.index("- name: Merge"):], msg="a merge by the Actions token would start no workflow")


if __name__ == "__main__":
    unittest.main()
