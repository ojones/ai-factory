# STEP 8.3: watch production. Each Managed App's recent Fly log and the owner's `escaped-defect` issues are read, and what repeats becomes a failure event (to_event.py)
# written to a file. Nothing is filed here: the events are judged by the Retrospective (STEP 6.7, `retrospective.judge_events`) and Try Fix writes and files the bug
# (`try_fix.file_events`), exactly as for a failed Build Run. The three run one after the other in production-feedback.yml.
#
# A repeat of an error that already has an open bug only adds a comment with the count. A defect report comes first: while an app has one to report, its logs wait.
#
# Usage: python -m bugs.scan_production <events.json>   (PYTHONPATH=orchestrator; env FLY_API_TOKEN, FACTORY_PAT, FACTORY_GH_TOKEN, GITHUB_REPOSITORY)
# Config: `limits.production_feedback` in agents/profiles.yml.
import json
import os
import sys
import time
from pathlib import Path

from request import find_intakes
from shared import app_state_record, config, github
from shared.console import log
from try_fix import event

from bugs import escaped_defects, flood_limits, route_bug, scan_logs, to_event

BUG_LABEL = "bug"


def counts(repo, token, app):
    # (open bugs for the app, bugs filed today, titles of the open ones, titles of all of them).
    open_now = find_intakes.intakes_with(repo, token, app, BUG_LABEL, "open")
    every = find_intakes.intakes_with(repo, token, app, BUG_LABEL, "all")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return len(open_now), sum(1 for i in every if i["createdAt"][:10] == today), open_now, every


def flag_states(repo, pat, app):
    out = github.run(["issue", "list", "--repo", f"{repo.split('/')[0]}/{app}", "--label", app_state_record.STATE_LABEL, "--state", "open", "--json", "body"], pat).stdout
    found = json.loads(out or "[]")
    return route_bug.flag_states(app_state_record.load(found[0]["body"]) if found else {})


def scan_defects(repo, pat, app, cfg, open_for_app, created_today, every):
    events = []
    for issue in escaped_defects.owner_defects(repo, pat, app):
        ev = to_event.defect_event(app, issue)
        if any(ev["key"] in i["title"] for i in every):
            continue
        if not flood_limits.defects_room(open_for_app, created_today, len(events), cfg):
            break
        events.append(ev)
    return events


def scan_errors(repo, token, app, cfg, open_for_app, created_today, open_now, logs, states):
    groups = scan_logs.group(scan_logs.parse_events(logs))
    keys = {fp: event.event_key("production_feedback", app, fp) for fp in groups}
    open_by_fp = {fp: i["number"] for fp, key in keys.items() for i in open_now if key in i["title"]}
    new, again = flood_limits.decide(groups, open_by_fp, open_for_app, created_today, cfg)
    for fp in again:
        github.run(["issue", "comment", str(open_by_fp[fp]), "--repo", repo, "--body", f"Seen {groups[fp]['count']} more times in the latest scan."], token)
    return [to_event.error_event(app, fp, groups[fp], groups[fp]["sample"], states) for fp in new]


def scan_app(repo, token, pat, app, cfg, logs=scan_logs.app_logs):
    # The failure events for one app.
    open_for_app, created_today, open_now, every = counts(repo, token, app)
    events = scan_defects(repo, pat, app, cfg, open_for_app, created_today, every)
    return events or scan_errors(repo, token, app, cfg, open_for_app, created_today, open_now, logs(app), flag_states(repo, pat, app))


def main(argv):
    repo = os.environ["GITHUB_REPOSITORY"]
    token, pat = os.environ["FACTORY_GH_TOKEN"], os.environ["FACTORY_PAT"]
    cfg = {**flood_limits.DEFAULTS, **((config.load().get("limits") or {}).get("production_feedback") or {})}
    events = []
    if not cfg["enabled"]:
        log("production feedback is off")
    else:
        for app in app_state_record.managed_apps(repo, token):
            try:
                found = scan_app(repo, token, pat, app, cfg)
                log(f"{app}: {len(found)} new event(s)")
                events += found
            except Exception as e:  # noqa: BLE001 - one app's failure never stops the scan of the others
                log(f"{app}: scan failed: {type(e).__name__}: {e}")
    event.dump(events, Path(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
