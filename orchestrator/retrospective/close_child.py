# Closing a child and moving the plan on (STEP 6.1, 6.3, 6.4). A child that finished is closed and starts the next one that is waiting; one that
# stopped loses `proceed-with-change`, so adding the label again retries it (a label that is still there cannot fire again). The children are the
# parent's sub-issues, and what a waiting child waits for is its GitHub blockers: it is ready when every blocker is closed. The last child to
# close closes the parent.
import os
import sys

from request import intake_labels
from shared import child_tickets
from shared.shell import sh


def ready_to_start(children, blockers):
    # The number of the one child to start now, as a list (empty when none). `children` are the parent's sub-issues, each {number, state,
    # labels}; `blockers(number)` gives that child's blockers as [{number, state}]. A child is ready when it is open, waiting, and every
    # blocker is closed. At most one starts, and none while another is in flight (open with `proceed-with-change`: one app runs one Build Run
    # at a time, and GitHub keeps only one pending run) or stalled (open with neither label: its run stopped, so it blocks the others until
    # it is retried or closed).
    open_ = [c for c in children if c["state"] == "OPEN"]
    if any(intake_labels.START in c["labels"] or child_tickets.WAIT not in c["labels"] for c in open_):
        return []
    ready = [c["number"] for c in open_ if all(b["state"] == "CLOSED" for b in blockers(c["number"]))]
    return sorted(ready)[:1]


def start_child(repo, pat, number):
    sh(["gh", "issue", "edit", str(number), "--repo", repo, "--remove-label", child_tickets.WAIT, "--add-label", intake_labels.START],
       env={**os.environ, "GH_TOKEN": pat}, check=False)


def advance(repo, pat, number, tickets=None):
    # After child `number` closed: close the parent if that was the last child, otherwise start the child that was waiting for it. Returns
    # {"started": [numbers], "parent_closed": bool}. An issue with no parent (a child of no plan) does nothing.
    parent = tickets.parent if tickets else child_tickets.parent_of(repo, number, pat)
    if not parent:
        return {"started": [], "parent_closed": False}
    tickets = tickets or child_tickets.ChildTickets(repo, parent, pat)
    children = tickets.children()
    if children and all(c["state"] == "CLOSED" for c in children):
        tickets.close(parent, "Every change set of this plan is done.")
        return {"started": [], "parent_closed": True}
    started = ready_to_start(children, tickets.blockers)
    for n in started:
        start_child(repo, pat, n)
    return {"started": started, "parent_closed": False}


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
    # python -m retrospective.close_child close <repo> <issue>: a child that is done is closed and the next one started (the staging workflow ends so).
    if len(argv) == 4 and argv[1] == "close":
        finish_update_intake(True, argv[2], argv[3], os.environ["FACTORY_PAT"])
        return 0
    print("usage: python -m retrospective.close_child close <repo> <issue number>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
