import json
import os
import re
import time

from shared import run_stops
from shared.shell import sh

LEDGER_LABEL = "factory-ledger"
LEDGER_RE = re.compile(r"^ledger (\d{4}-\d{2}-\d{2}) (\S+) (\d+(?:\.\d+)?) run:(\S+)\s*$")


def ledger_line(day, app, usd, run_id):
    return f"ledger {day} {app} {usd:.4f} run:{run_id}"


def ledger_total(comment_bodies, day):
    seen, total = set(), 0.0
    for body in comment_bodies:
        m = LEDGER_RE.match((body or "").strip())
        if m and m.group(1) == day and m.group(4) not in seen:
            seen.add(m.group(4))
            total += float(m.group(3))
    return round(total, 4)


def read_stdout(proc):
    if proc.returncode != 0:
        raise run_stops.NeedsHuman("other", "could not read the spend ledger, so the daily cap cannot be checked; try again later")
    return proc.stdout


def open_ledger_number(list_issues):
    found = json.loads(read_stdout(list_issues) or "[]")
    return found[0]["number"] if found else None


def create_ledger_issue(repo, env):
    sh(["gh", "label", "create", LEDGER_LABEL, "--repo", repo, "--color", "ededed",
        "--description", "One comment per Build Run with what it spent"], env=env, check=False)
    made = sh(["gh", "issue", "create", "--repo", repo, "--label", LEDGER_LABEL, "--title", "Factory spend ledger", "--body",
               "One comment per finished Build Run (`ledger <date> <app> <usd> run:<id>`). The Orchestrator adds the day's "
               "lines to check `limits.daily_cost_cap_usd`. Do not edit or close this issue."], env=env).stdout
    created = re.search(r"/issues/(\d+)", made)
    if not created:
        raise RuntimeError("gh issue create printed no issue URL")
    return int(created.group(1))


def post_ledger_line(line, repo, env):
    listed = sh(["gh", "issue", "list", "--repo", repo, "--label", LEDGER_LABEL, "--state", "open", "--json", "number"], env=env, check=False)
    number = open_ledger_number(listed) or create_ledger_issue(repo, env)
    sh(["gh", "issue", "comment", str(number), "--repo", repo, "--body", line], env=env)


def record_spend_in_ledger(d, repo, run_id, token):
    if not d.get("spent_usd"):
        return
    line = ledger_line(time.strftime("%Y-%m-%d", time.gmtime()), d["app"], d["spent_usd"], run_id)
    try:
        post_ledger_line(line, repo, {**os.environ, "GH_TOKEN": token})
    except (RuntimeError, OSError, ValueError, run_stops.NeedsHuman) as e:
        print(f"::warning::spend not in the ledger, the daily cap undercounts it; add this comment to the {LEDGER_LABEL} issue: {line} ({type(e).__name__})", flush=True)


def todays_spend(run, repo, token, day=None):
    day = day or time.strftime("%Y-%m-%d", time.gmtime())
    number = open_ledger_number(run(["issue", "list", "--repo", repo, "--label", LEDGER_LABEL, "--state", "open", "--json", "number"], token))
    if number is None:
        return None
    out = read_stdout(run(["api", f"repos/{repo}/issues/{number}/comments?per_page=100&since={day}T00:00:00Z", "--paginate", "--jq", ".[].body"], token))
    return ledger_total(out.split("\n"), day)
