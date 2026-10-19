# The three ways a run stops that are neither a good ending nor a crash. Raised by the Agent runtime and by the Build Run.

class BudgetExhausted(Exception):
    pass


class ProviderBlocked(Exception):
    # The model provider refuses every request because the account has no balance (HTTP 402). Nothing a retry, a fix request
    # or a retrospective Agent does can help until someone tops it up, and each of them would fail the same way.
    pass


class NeedsHuman(Exception):
    # kind: round_limit | time_limit | stuck | pipeline | other

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
