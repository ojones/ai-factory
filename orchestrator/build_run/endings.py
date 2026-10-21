# How a Build Run can stop early, as exceptions the sequencing catches, and how a NeedsHuman stop is reported.



class Refused(Exception):
    # The request cannot be built here (a real secret in public text, or the planner judged it infeasible). The run ends `refused`: nothing
    # was built, so nothing is rolled back, retried or filed as a failure.
    pass


class AwaitingSecret(Exception):
    # The plan declares secrets that are not all set as GitHub Actions secrets on the app's repository yet. The run ends `awaiting_secret`:
    # nothing was built, and it is not a failure, so nothing is retried or learned from. Adding `proceed-with-change` again checks again.
    pass


class Regression(Exception):
    # The tester saw behaviour that was live before this change stop working (`test_impact`). finalize rolls the deploy back through CI.
    pass


class PipelineFix(Exception):
    # CI or the deploy failed because of the code, and the coder has committed a fix locally. The fix goes through the reviewer
    # before it is pushed, like any other commit; `head` is that local commit.

    def __init__(self, head):
        super().__init__(head)
        self.head = head


NEAR_CAP = 0.9  # spend at or above this share of the cap makes an Agent's failure a budget ending


def ending_for(kind, message, spent, cap):
    # How a NeedsHuman stop is reported. An Agent whose credential has run dry just fails to produce its file (first seen
    # when a tester ran out of a $0.08 cap and the run was reported as `needs_human: no valid output file`), so a stop of
    # kind `other` with the cap already spent is a budget ending, not a mystery.
    named = {"time_limit": "time_limit", "round_limit": "round_limit", "stuck": "stuck"}.get(kind)
    if named:
        return named, message
    if cap and spent is not None and spent >= NEAR_CAP * cap:
        return "budget_exhausted", f"${spent:.4f} spent against a ${cap:.2f} cap, and then: {message}"
    return "needs_human", message
