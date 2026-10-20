import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import child_tickets  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
KIND_STAGING = '"kind":"staging"'


def job_if(name):
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
    return " ".join(next(iter(wf["jobs"].values()))["if"].split())


class RouteTheChildByKind(unittest.TestCase):
    # STEP 2.6: a child with `proceed-with-change` goes to App Staging when its marker says `kind: staging` and to a Build Run otherwise, never to both. The workflows
    # decide with a text match on the body, so the match is checked against the marker the planner actually writes.
    def test_the_text_both_workflows_match_is_what_the_marker_renders_for_a_staging_child(self):
        self.assertIn(KIND_STAGING, child_tickets.render_marker({"parent": 7, "cs": "CS-1", "kind": "staging"}))
        self.assertNotIn(KIND_STAGING, child_tickets.render_marker({"parent": 7, "cs": "CS-2", "kind": "update"}))

    def test_app_staging_takes_only_a_staging_child_and_the_build_run_start_takes_everything_else(self):
        staging, update = job_if("app-staging.yml"), job_if("update-app-intake.yml")
        self.assertIn(f"contains(github.event.issue.body, '{KIND_STAGING}')", staging)
        self.assertNotIn(f"!contains(github.event.issue.body, '{KIND_STAGING}')", staging)
        self.assertIn(f"!contains(github.event.issue.body, '{KIND_STAGING}')", update)
        for cond in (staging, update):
            self.assertIn("github.event.label.name == 'proceed-with-change'", cond)  # only the start label routes anything

    def test_a_benchmark_child_is_not_started_by_the_production_workflow(self):
        self.assertIn("!contains(github.event.issue.labels.*.name, 'benchmark')", job_if("update-app-intake.yml"))  # its Build Run is dispatched by the benchmark


if __name__ == "__main__":
    unittest.main()
