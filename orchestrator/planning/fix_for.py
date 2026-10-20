# STEP 2.1, 2.4: planning a bug Intake that fixes a failed child (its body carries a `fix-for` marker, shared/child_tickets.read_fix_for). The plan is exactly one
# change set, behind exactly the failed story's flag (or none when the failed child had none), so a fix keeps one story, one flag and one rollback. The planner is
# told to plan one slice, the plan gate refuses more than one, and the child is filed with `flag_story`, `fix_for` and `fix_attempt` so the Build Run names the
# flag after the failed story and the Retrospective counts the attempts. The failed child is already blocked by the bug Intake (try_fix/file_bug.py), so nothing
# here blocks anything.
MAX_CHANGE_SETS = 1

NOTE = ("This request is a fix for a change set that failed after it was built. Plan exactly ONE change set: the smallest change that satisfies the "
        "requirements below. Do not split it, and do not add features. The original instructions of the change set that failed are in the request; "
        "the new change set keeps the same feature flag, so do not plan a new one.\n\n")


def task_for(task, fix):
    return NOTE + task if fix else task


def max_change_sets(fix, default):
    return MAX_CHANGE_SETS if fix else default


def apply(cs, fix):
    # The change set as it is filed for a fix: the failed child's flag setting, not the planner's.
    return dict(cs, flag=bool(fix["flag"])) if fix else cs
