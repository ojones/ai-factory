import json
import os
import sys
from datetime import datetime, timedelta, timezone

from retrospective import close_child
from shared import child_tickets, config, github
from try_fix import resume_after_merge

from factory_change import markers, open_pr, pause, stop

WATCHING = "factory-change-watching"
CLEAN = "factory-change-clean"
TRIPPED = "factory-change-tripped"
DRIFT_LABEL = "model-drift"
INEFFECTIVE = "fix-ineffective"
SAME_FINDING = "same-finding"


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def view_json(repo, token, kind, number, fields):
    return json.loads(github.run([kind, "view", str(number), "--repo", repo, "--json", fields], token).stdout or "{}")


def list_json(repo, token, args, fields):
    return json.loads(github.run([*args, "--repo", repo, "--json", fields], token).stdout or "[]")


def recurred(repo, token, intake, merged_at):
    doc = view_json(repo, token, "issue", intake, "labels,comments")
    seen = [c for c in doc.get("comments") or [] if (c.get("body") or "").startswith("**Seen again") and parse_time(c["createdAt"]) > merged_at]
    return bool(seen)


def drifted(repo, token, merged_at):
    found = list_json(repo, token, ["issue", "list", "--label", DRIFT_LABEL, "--state", "open"], "number,createdAt")
    return any(parse_time(i["createdAt"]) > merged_at for i in found)


def later_runs(repo, token, intake, merged_at):
    runs = [{"failed": True, "stage": SAME_FINDING}] if intake and recurred(repo, token, intake, merged_at) else []
    return runs + [{"regression": True}] if drifted(repo, token, merged_at) else runs


def ineffective_streak(repo, token):
    merged = list_json(repo, token, ["pr", "list", "--state", "merged", "--label", open_pr.PR_LABEL, "--limit", "5"], "number,body,mergedAt")
    streak = 0
    for pr in sorted(merged, key=lambda p: p["mergedAt"], reverse=True):
        intake = intake_of(repo, token, markers.read(pr["body"], markers.CHILD))
        names = {x["name"] for x in view_json(repo, token, "issue", intake, "labels").get("labels") or []} if intake else set()
        if INEFFECTIVE not in names:
            break
        streak += 1
    return streak


def intake_of(repo, token, child):
    return child_tickets.parent_of(repo, child, token) if child else None


def mark(repo, token, number, add, remove=WATCHING):
    github.run(["pr", "edit", str(number), "--repo", repo, "--add-label", add, "--remove-label", remove], token)


def start_watching(repo, token, pr_number, body):
    github.ensure_label(repo, WATCHING, token, "fbca04", "A merged Factory Change under watch")
    github.run(["pr", "edit", str(pr_number), "--repo", repo, "--add-label", WATCHING], token)
    child = markers.read(body, markers.CHILD)
    return stop.end(repo, token, child, stop.MERGED, f"#{pr_number} is merged; it is watched for the next {config.load()['limits']['factory_change_watch_hours']} hours before this closes")


def trip(repo, pat, pr, reason):
    github.ensure_label(repo, TRIPPED, pat, "b60205", "A merged Factory Change that the watch found failing; it is fixed forward")
    mark(repo, pat, pr["number"], TRIPPED)
    pause.pause(repo, pat, reason, f"#{pr['number']} stays in main and is fixed forward: the finding is on its Intake and a person clears the pause to let a new change be planned.")
    return stop.PAUSED


def settle_clean(repo, pat, pr):
    child = markers.read(pr["body"], markers.CHILD)
    github.ensure_label(repo, CLEAN, pat, "0e8a16", "A Factory Change that held")
    mark(repo, pat, pr["number"], CLEAN)
    github.run(["issue", "close", str(child), "--repo", repo, "--reason", "completed"], pat)
    close_child.advance(repo, pat, int(child))
    intake = intake_of(repo, pat, child)
    if intake:
        resume_after_merge.resume(repo, pat, pat, view_json(repo, pat, "issue", intake, "body").get("body", ""))
    return stop.MERGED


def judge(repo, pat, pr, now, hours):
    merged_at = parse_time(pr["mergedAt"])
    child = markers.read(pr["body"], markers.CHILD)
    intake = intake_of(repo, pat, child)
    reason = pause.breaker_reason(SAME_FINDING, later_runs(repo, pat, intake, merged_at), ineffective_streak(repo, pat))
    if reason:
        return trip(repo, pat, pr, reason)
    return settle_clean(repo, pat, pr) if now >= merged_at + timedelta(hours=hours) else None


def sweep(repo, pat, now=None, hours=None):
    now = now or datetime.now(timezone.utc)
    hours = hours if hours is not None else int(config.load()["limits"]["factory_change_watch_hours"])
    watched = list_json(repo, pat, ["pr", "list", "--state", "merged", "--label", WATCHING], "number,body,mergedAt")
    return {pr["number"]: judge(repo, pat, pr, now, hours) for pr in watched}


def main(argv):
    env = os.environ
    if argv[1:] == ["merged"]:
        start_watching(env["GITHUB_REPOSITORY"], env["FACTORY_PAT"], env["PR_NUMBER"], env.get("PR_BODY", ""))
    else:
        print(sweep(env["GITHUB_REPOSITORY"], env["FACTORY_PAT"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
