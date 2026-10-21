MAX_CHANGE_SETS = 1

NOTE = ("This request is a fix for a change set that failed after it was built. Plan exactly ONE change set: the smallest change that satisfies the "
        "requirements below. Do not split it, and do not add features. The original instructions of the change set that failed are in the request.\n\n")


def task_for(task, fix):
    return NOTE + task if fix else task


def max_change_sets(fix, default):
    return MAX_CHANGE_SETS if fix else default
