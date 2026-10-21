import json
import os
import sys
import time
from pathlib import Path

from flag_lifecycle import dark_feature
from request import intake_labels
from shared import agent_output, config, outcomes, rollback, spend_ledger
from shared.shell import sh

from retrospective import app_state, close_child, run_audit, run_summary


def crash_report(app, issue_number, run_url):
    return {"app": app, "issue_number": issue_number, "run_url": run_url, "outcome": "crash",
            "message": "no state file was written; the Build Run failed before its first stage", "cap_usd": 0,
            "spent_usd": 0.0, "head_sha": None, "review_passes": 0, "stages": [], "release": None, "blocking": [],
            "commits": [], "base_sha": None}


def retry_hint(d, ok):
    if ok or d["outcome"] in outcomes.ANSWERED:
        return ""
    if d["outcome"] == "provider_blocked":
        return f"\n\nOnce the provider balance is topped up, add `{intake_labels.START}` again to retry."
    return f"\n\nEdit this issue if the request needs to change, then add `{intake_labels.START}` again to retry."


class Finalize:
    def __init__(self):
        self.work = Path(os.environ["BUILD_RUN_DIR"])
        self.app, self.repo = os.environ["APP_NAME"], os.environ["GITHUB_REPOSITORY"]
        self.pat, self.ftoken = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
        self.owner = self.repo.split("/")[0]
        self.run_id = os.environ.get("GITHUB_RUN_ID", "0")
        self.run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{self.repo}/actions/runs/{self.run_id}"

    def load_report(self):
        d = agent_output.load_json(self.work / "state.json")
        if d is None:
            return crash_report(self.app, os.environ["ISSUE_NUMBER"], self.run_url)
        if d["outcome"] == "running":
            d["message"] = d["message"] or "the Build Run process ended without recording an outcome (cancelled or killed)"
        return d

    def roll_back(self, d):
        try:
            rollback.rollback_failed_run(d, self.pat, config.load()["limits"])
        except Exception as e:  # noqa: BLE001
            d["rollback"] = {"status": "failed", "reason": f"{type(e).__name__}: {str(e)[:300]}"}

    def write_reports(self, d):
        (self.work / "state.json").write_text(json.dumps(d, indent=2))
        summary = run_summary.render_summary(d)
        (self.work / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.work / "artifacts" / "build-run-report.json").write_text(json.dumps(d, indent=2))
        with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as f:
            f.write(summary)
        return summary

    def file_failure_issue(self, d, summary):
        body = f"{d['message']}\n\n**Build Run**: {self.run_url}\n**Spent**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f}\n\n" + summary
        (self.work / "issue-body.md").write_text(body)
        sh(["gh", "issue", "create", "--repo", f"{self.owner}/{self.app}", "--title", outcomes.TITLES.get(d["outcome"], "Build Run: crash"),
            "--body-file", str(self.work / "issue-body.md")], env={**os.environ, "GH_TOKEN": self.pat}, check=False)

    def comment_outcome(self, d, ok):
        text = f"**Build Run {'finished' if ok else 'stopped'}: `{d['outcome']}`.** {d['message']} ([run]({self.run_url})){retry_hint(d, ok)}"
        sh(["gh", "issue", "comment", d["issue_number"], "--repo", self.repo, "--body", text], env={**os.environ, "GH_TOKEN": self.ftoken}, check=False)

    def run(self):
        d = self.load_report()
        d["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.roll_back(d)
        d["audit"] = run_audit.audit_report(d)
        summary = self.write_reports(d)
        ok = d["outcome"] in outcomes.OK
        spend_ledger.record_spend_in_ledger(d, self.repo, self.run_id, self.ftoken)
        app_state.update_state_issues(d, self.repo, self.pat, self.ftoken)
        if not ok and d["outcome"] not in outcomes.ANSWERED:
            self.file_failure_issue(d, summary)
        self.comment_outcome(d, ok)
        dark_feature.label_dark_feature(d, self.repo, self.ftoken)
        close_child.finish_update_intake(ok, self.repo, d["issue_number"], self.pat)
        return 0 if ok else 1


def finalize():
    return Finalize().run()


if __name__ == "__main__":
    sys.exit(finalize())
