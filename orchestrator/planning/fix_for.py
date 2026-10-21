# STEP 2.1, 2.4: planning a bug Intake that fixes a failed child (its body carries a `fix-for` marker, shared/child_tickets.read_fix_for). The plan is exactly one
# change set, an ordinary child: the planner decides its flag like any other, and the Build Run names it `issue-<own number>`. The planner is told to plan one
# slice, the plan gate refuses more than one, and the child is filed with `fix_for` and `fix_attempt` so the Retrospective counts the attempts. The failed child
# is already blocked by the bug Intake (try_fix/file_bug.py), so nothing here blocks anything.
MAX_CHANGE_SETS = 1

NOTE = ("This request is a fix for a change set that failed after it was built. Plan exactly ONE change set: the smallest change that satisfies the "
        "requirements below. Do not split it, and do not add features. The original instructions of the change set that failed are in the request.\n\n")


def task_for(task, fix):
    return NOTE + task if fix else task


def max_change_sets(fix, default):
    return MAX_CHANGE_SETS if fix else default
