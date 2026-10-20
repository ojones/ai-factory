# The spend ledger: one comment per finished Build Run on the `factory-ledger` issue in ai-factory, summed per UTC day to enforce the daily cap.
import json
import os
import re
import time

from shared.shell import sh

LEDGER_LABEL = "factory-ledger"
LEDGER_RE = re.compile(r"^ledger (\d{4}-\d{2}-\d{2}) (\S+) (\d+(?:\.\d+)?) run:(\S+)\s*$")


def ledger_line(day, app, usd, run_id):
    # The comment a finished Build Run adds to the spend ledger issue.
    return f"ledger {day} {app} {usd:.4f} run:{run_id}"


def ledger_total(comment_bodies, day):
    # USD recorded in the ledger for `day` (UTC date string). A line that is not a ledger line, or is for
    # another day, counts for nothing; a run id seen twice counts once.
    seen, total = set(), 0.0
    for body in comment_bodies:
        m = LEDGER_RE.match((body or "").strip())
        if m and m.group(1) == day and m.group(4) not in seen:
            seen.add(m.group(4))
            total += float(m.group(3))
    return round(total, 4)


def record_spend_in_ledger(d, repo, run_id, token):
    # Add this run's spend to the ledger issue (best effort: a failure here never changes the run's outcome).
    try:
        if not d.get("spent_usd"):
            return
        env = {**os.environ, "GH_TOKEN": token}
        out = sh(["gh", "issue", "list", "--repo", repo, "--label", LEDGER_LABEL, "--state", "open", "--json", "number"],
                 env=env, check=False).stdout
        found = json.loads(out or "[]")
        if not found:
            sh(["gh", "label", "create", LEDGER_LABEL, "--repo", repo, "--color", "ededed",
                "--description", "One comment per Build Run with what it spent"], env=env, check=False)
            made = sh(["gh", "issue", "create", "--repo", repo, "--label", LEDGER_LABEL, "--title", "Factory spend ledger", "--body",
                       "One comment per finished Build Run (`ledger <date> <app> <usd> run:<id>`). The Orchestrator adds the day's "
                       "lines to check `limits.daily_cost_cap_usd`. Do not edit or close this issue."], env=env, check=False).stdout
            m = re.search(r"/issues/(\d+)", made)
            found = [{"number": int(m.group(1))}] if m else []
        if found:
            sh(["gh", "issue", "comment", str(found[0]["number"]), "--repo", repo, "--body",
                ledger_line(time.strftime("%Y-%m-%d", time.gmtime()), d["app"], d["spent_usd"], run_id)], env=env, check=False)
    except Exception as e:  # noqa: BLE001
        print(f"could not record spend in the ledger: {type(e).__name__}", flush=True)


def todays_spend(run, repo, token, day=None):
    # USD the ledger records for `day` (default today, UTC), or None before any run has made the ledger issue. `run(args, token)` runs `gh`.
    day = day or time.strftime("%Y-%m-%d", time.gmtime())
    found = json.loads(run(["issue", "list", "--repo", repo, "--label", LEDGER_LABEL, "--state", "open", "--json", "number"], token).stdout or "[]")
    if not found:
        return None
    out = run(["api", f"repos/{repo}/issues/{found[0]['number']}/comments?per_page=100&since={day}T00:00:00Z", "--paginate", "--jq", ".[].body"],
              token).stdout
    return ledger_total((out or "").split("\n"), day)
