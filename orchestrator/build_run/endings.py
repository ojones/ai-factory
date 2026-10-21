class Refused(Exception):
    pass


class AwaitingSecret(Exception):
    pass


class Regression(Exception):
    pass


class PipelineFix(Exception):

    def __init__(self, head):
        super().__init__(head)
        self.head = head


NEAR_CAP = 0.9


def ending_for(kind, message, spent, cap):
    named = {"time_limit": "time_limit", "round_limit": "round_limit", "stuck": "stuck"}.get(kind)
    if named:
        return named, message
    if cap and spent is not None and spent >= NEAR_CAP * cap:
        return "budget_exhausted", f"${spent:.4f} spent against a ${cap:.2f} cap, and then: {message}"
    return "needs_human", message
