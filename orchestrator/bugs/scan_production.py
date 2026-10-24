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
    open_for_app, created_today, open_now, every = counts(repo, token, app)
    events = scan_defects(repo, pat, app, cfg, open_for_app, created_today, every)
    return events or scan_errors(repo, token, app, cfg, open_for_app, created_today, open_now, logs(app), flag_states(repo, pat, app))


def main(argv):
    repo = os.environ["GITHUB_REPOSITORY"]
    token, pat = os.environ["FACTORY_GH_TOKEN"], os.environ["FACTORY_PAT"]
    limits = config.load().get("limits") or {}
    cfg = flood_limits.settings(limits)
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
