class BudgetExhausted(Exception):
    pass


class ProviderBlocked(Exception):
    pass


class NeedsHuman(Exception):

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class FlagMissing(Exception):
    pass
