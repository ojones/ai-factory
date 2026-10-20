# infra/app-staging/stage.sh in its dry-run mode, with a fake `gh` first on the PATH: the child is read and checked, what would be staged is printed, and nothing
# is created (no Fly, GrowthBook, repository or secret call is made; only reads and, on a refusal, a comment).
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import child_tickets  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["GH_LOG"], "a") as f:
    f.write(json.dumps(args) + "\\n")
data = json.load(open(os.environ["GH_DATA"]))
if args[:2] == ["issue", "view"]:
    print(json.dumps(data["issues"][args[2]]))
elif args[0] == "api" and args[1].endswith("/parent"):
    if data["parent"] is None:
        print("gh: No parent issue found (HTTP 404)", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(data["parent"]))
elif args[:2] == ["issue", "list"]:
    print(json.dumps(data.get("started", [])))
elif args[:2] == ["run", "list"]:
    print("[]")
"""


class DryRun(unittest.TestCase):
    def run_script(self, kind="staging", parent="default", app="notes"):
        marker = child_tickets.render_marker({"parent": 7, "cs": "CS-1", "kind": kind})
        child = {"number": 12, "labels": [], "body": f"{marker}\n\n### App name\n\n{app}\n\n### What should change?\n\nStage it\n"}
        data = {"issues": {"12": child, "7": {"body": "### What should be built?\n\nA notes app\n\n### Cost cap override (USD)\n\n$3\n"}},
                "parent": {"number": 7, "state": "open"} if parent == "default" else parent}
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(FAKE_GH)
            gh.chmod(0o755)
            (Path(tmp) / "data.json").write_text(json.dumps(data))
            env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_LOG": str(Path(tmp) / "log"), "GH_DATA": str(Path(tmp) / "data.json"),
                   "STAGING_DRY_RUN": "1", "ISSUE_NUMBER": "12", "ISSUE_TITLE": "notes: stage", "ISSUE_BODY": "", "FACTORY_REPO": "o/f",
                   "RUN_URL": "u", "GH_TOKEN": "t", "FACTORY_PAT": "p", "FLY_API_TOKEN": "f", "GROWTHBOOK_ADMIN_PAT": "g", "PREVIEW_MASTER_SECRET": "m",
                   "PYTHONPATH": str(ROOT / "orchestrator")}
            p = subprocess.run(["bash", str(ROOT / "infra/app-staging/stage.sh")], env=env, capture_output=True, text=True, timeout=60)
            calls = [json.loads(line) for line in (Path(tmp) / "log").read_text().splitlines()] if (Path(tmp) / "log").exists() else []
        return p, calls

    def test_a_staging_child_is_read_and_nothing_is_changed(self):
        p, calls = self.run_script()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("dry run: would stage app notes for Intake #7 (child #12), repo marker 'Intake: o/f#7', cost cap $3.00 (override)", p.stdout)
        changing = [c for c in calls if c[:2] in (["issue", "edit"], ["issue", "comment"], ["issue", "close"], ["label", "create"])]
        self.assertEqual(changing, [])

    def test_a_child_that_is_not_a_staging_child_is_refused_with_a_comment_and_loses_the_start_label(self):
        p, calls = self.run_script(kind="update")
        self.assertEqual(p.returncode, 1)
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertIn("not a staging child", comment[-1])
        self.assertTrue(any(c[:2] == ["issue", "edit"] and "proceed-with-change" in c for c in calls))

    def test_a_staging_child_with_no_parent_is_refused(self):
        p, calls = self.run_script(parent=None)
        self.assertEqual(p.returncode, 1)
        self.assertIn("not a sub-issue", next(c for c in calls if c[:2] == ["issue", "comment"])[-1])

    def test_the_script_has_no_ready_for_staging_label(self):
        text = (ROOT / "infra/app-staging/stage.sh").read_text()
        self.assertIn("--remove-label proceed-with-change", text)
        self.assertNotIn("ready-for-staging", text)


if __name__ == "__main__":
    unittest.main()
