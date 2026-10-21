# The last step of every Build Run (STEP 6.2): roll a regression back, audit the Report, write the Summary, record the spend and the App State,
# open the failure Issue, comment on the story, and close the child. Always runs, even after a crash or a cancel.
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


def finalize():
    work = Path(os.environ["BUILD_RUN_DIR"])
    app = os.environ["APP_NAME"]
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '0')}"
    d = agent_output.load_json(work / "state.json")
    if d is None:
        d = {"app": app, "issue_number": os.environ["ISSUE_NUMBER"], "run_url": run_url, "outcome": "crash",
             "message": "no state file was written; the Build Run failed before its first stage", "cap_usd": 0,
             "spent_usd": 0.0, "head_sha": None, "review_passes": 0, "stages": [], "release": None, "blocking": [],
             "commits": [], "base_sha": None}
    elif d["outcome"] == "running":
        d["message"] = d["message"] or "the Build Run process ended without recording an outcome (cancelled or killed)"
    d["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        rollback.rollback_failed_run(d, os.environ["FACTORY_PAT"], config.load()["limits"])
    except Exception as e:  # noqa: BLE001
        d["rollback"] = {"status": "failed", "reason": f"{type(e).__name__}: {str(e)[:300]}"}
    d["audit"] = run_audit.audit_report(d)
    # The retrospective reads state.json, so the final state (audit, rollback) has to be saved there too.
    (work / "state.json").write_text(json.dumps(d, indent=2))
    summary = run_summary.render_summary(d)
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    (work / "artifacts" / "build-run-report.json").write_text(json.dumps(d, indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as f:
        f.write(summary)
    ok = d["outcome"] in outcomes.OK
    spend_ledger.record_spend_in_ledger(d, os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_RUN_ID", "0"), os.environ["FACTORY_GH_TOKEN"])
    pat, ftoken = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    app_state.update_state_issues(d, os.environ["GITHUB_REPOSITORY"], pat, ftoken)
    if not ok and d["outcome"] not in outcomes.ANSWERED:  # a refusal is answered on the Intake issue; there is nothing in the app repo to report
        body = f"{d['message']}\n\n**Build Run**: {run_url}\n**Spent**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f}\n\n" + summary
        (work / "issue-body.md").write_text(body)
        sh(["gh", "issue", "create", "--repo", f"{owner}/{app}", "--title", outcomes.TITLES.get(d["outcome"], "Build Run: crash"),
            "--body-file", str(work / "issue-body.md")], env={**os.environ, "GH_TOKEN": pat}, check=False)
    retry = ("" if ok else
             f"\n\nOnce the provider balance is topped up, add `{intake_labels.START}` again to retry." if d["outcome"] == "provider_blocked"
             else "" if d["outcome"] in outcomes.ANSWERED  # the message already says how to try again
             else f"\n\nEdit this issue if the request needs to change, then add `{intake_labels.START}` again to retry.")
    sh(["gh", "issue", "comment", d["issue_number"], "--repo", os.environ["GITHUB_REPOSITORY"], "--body",
        f"**Build Run {'finished' if ok else 'stopped'}: `{d['outcome']}`.** {d['message']} ([run]({run_url})){retry}"],
       env={**os.environ, "GH_TOKEN": ftoken}, check=False)
    dark_feature.label_dark_feature(d, os.environ["GITHUB_REPOSITORY"], ftoken)
    close_child.finish_update_intake(ok, os.environ["GITHUB_REPOSITORY"], d["issue_number"], pat)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(finalize())
