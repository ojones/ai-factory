# The one list of how a Build Run can end, and which endings are good, answered or neither.
OK = ("released", "nothing_to_release", "planned")  # `planned`: an update was split into child issues, each its own Build Run
ANSWERED = ("refused", "awaiting_secret")  # an answer to the requester, not a failure: nothing is retried, filed or learned from
PROVIDER_BLOCKED = "provider_blocked"
WATCHDOG_DISABLED = "watchdog_disabled"
FLAG_MISSING = "flag_missing"  # deployed dark behind a flag that does not exist, so nothing can turn it on


def is_ok(outcome):
    return outcome in OK


def is_answered(outcome):
    return outcome in ANSWERED
