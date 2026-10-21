import json
import os
import sys

from request import intake_labels
from shared import child_tickets, github
from shared.shell import sh


def ready_to_start(children, blockers):
    open_ = [c for c in children if c["state"] == "OPEN"]
    if any(intake_labels.START in c["labels"] or child_tickets.WAIT not in c["labels"] for c in open_):
        return []
    ready = [c["number"] for c in open_ if all(b["state"] == "CLOSED" for b in blockers(c["number"]))]
    return sorted(ready)[:1]


def start_child(repo, pat, number):
    sh(["gh", "issue", "edit", str(number), "--repo", repo, "--remove-label", child_tickets.WAIT, "--add-label", intake_labels.START],
       env={**os.environ, "GH_TOKEN": pat}, check=False)


def settle_fix(repo, pat, parent, run=None):
    run = run or github.run
    p = run(["issue", "view", str(parent), "--repo", repo, "--json", "body"], pat)
    fix = child_tickets.read_fix_for(json.loads(p.stdout or "{}").get("body") if p.returncode == 0 else "")
    if not fix:
        return []
    run(["issue", "comment", str(fix["fix_for"]), "--repo", repo, "--body",
         f"The fix for this change set is done (#{parent} is closed). It runs again behind its own flag, now with the fix in `main`."], pat)
    return advance_plan(repo, pat, fix["origin_parent"])["started"]


def advance_plan(repo, pat, parent, tickets=None):
    tickets = tickets or child_tickets.ChildTickets(repo, parent, pat)
    children = tickets.children()
    if children and all(c["state"] == "CLOSED" for c in children):
        tickets.close(parent, "Every change set of this plan is done.")
        return {"started": settle_fix(repo, pat, parent, getattr(tickets, "_run", None)), "parent_closed": True}
    started = ready_to_start(children, tickets.blockers)
    for n in started:
        start_child(repo, pat, n)
    return {"started": started, "parent_closed": False}


def advance(repo, pat, number, tickets=None):
    parent = tickets.parent if tickets else child_tickets.parent_of(repo, number, pat)
    if not parent:
        return {"started": [], "parent_closed": False}
    return advance_plan(repo, pat, parent, tickets)


def finish_update_intake(ok, repo, number, pat):
    try:
        env = {**os.environ, "GH_TOKEN": pat}
        if ok:
            sh(["gh", "issue", "close", str(number), "--repo", repo, "--reason", "completed"], env=env, check=False)
            advance(repo, pat, number)
        else:
            sh(["gh", "issue", "edit", str(number), "--repo", repo, "--remove-label", intake_labels.START], env=env, check=False)
    except Exception as e:  # noqa: BLE001
        print(f"could not finish the Update App Intake: {type(e).__name__}", flush=True)


def main(argv):
    if len(argv) == 4 and argv[1] == "close":
        finish_update_intake(True, argv[2], argv[3], os.environ["FACTORY_PAT"])
        return 0
    print("usage: python -m retrospective.close_child close <repo> <issue number>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
