# The one list of how a Build Run can end, and which endings are good, answered or neither.
OK = ("released", "nothing_to_release")
ANSWERED = ("refused", "awaiting_secret")  # an answer to the requester, not a failure: nothing is retried, filed or learned from
PROVIDER_BLOCKED = "provider_blocked"
WATCHDOG_DISABLED = "watchdog_disabled"
FLAG_MISSING = "flag_missing"  # deployed dark behind a flag that does not exist, so nothing can turn it on


def is_ok(outcome):
    return outcome in OK


def is_answered(outcome):
    return outcome in ANSWERED


# The title of the failure Issue filed in the app's repo for an ending that is not good or answered.
TITLES = {
    "flag_missing": "Build Run: not released (the flag the change is behind does not exist)",
    "budget_exhausted": "Build Run: budget exhausted",
    "round_limit": "Build Run: needs human (review round limit reached)",
    "time_limit": "Build Run: needs human (time limit reached)",
    "provider_blocked": "Build Run: model provider blocked (account has no balance)",
    "refused": "Build Run: request refused (the Factory cannot build it)",
    "stuck": "Build Run: needs human (no progress across rounds)",
    "watchdog_disabled": "Build Run: release switched off by the watchdog",
    "regression": "Build Run: regression found by the tester (deploy rolled back)",
    "needs_human": "Build Run: needs human",
    "crash": "Build Run: crash",
    "running": "Build Run: crash (it ended without finishing)",
}
