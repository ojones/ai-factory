import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent.parent


def condition(name):
    wf = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    return " ".join(next(iter(wf["jobs"].values()))["if"].split()), wf


class Triggers(unittest.TestCase):
    def test_a_staging_child_is_staged_and_never_started_as_a_build_run(self):
        staged, wf = condition("app-staging.yml")
        self.assertIn("github.event.label.name == 'proceed-with-change'", staged)
        self.assertIn("contains(github.event.issue.body, '\"kind\":\"staging\"')", staged)
        build, _ = condition("update-app-intake.yml")
        self.assertIn("!contains(github.event.issue.body, '\"kind\":\"staging\"')", build)

    def test_nothing_but_a_staging_child_stages_an_app_and_one_app_goes_at_a_time(self):
        staged, wf = condition("app-staging.yml")
        self.assertNotIn("ready-for-staging", staged)
        self.assertNotIn("new-app-intake", staged)
        job = next(iter(wf["jobs"].values()))
        self.assertEqual(job["concurrency"]["group"], "app-staging", msg="one app through staging at a time")
        self.assertIs(job["concurrency"]["cancel-in-progress"], False)

    def test_no_ready_for_staging_label_is_left_anywhere_in_the_workflows_or_the_script(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            self.assertNotIn("ready-for-staging", path.read_text(), path.name)
        self.assertNotIn("ready-for-staging", (ROOT / "infra/app-staging/stage.sh").read_text())


if __name__ == "__main__":
    unittest.main()
