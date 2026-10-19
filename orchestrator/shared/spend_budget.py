# The run's one cap, enforced and metered by scoped model-provider credentials.
from shared import http_client, provider
from shared.run_stops import BudgetExhausted, ProviderBlocked


class Budget:
    # The run's one cap, enforced and metered by DeepInfra scoped JWTs.
    #
    # A spending-limited JWT can carry only one model, so each Agent invocation gets its own
    # single-model JWT limited to what is left of the run's cap. DeepInfra refuses the first call
    # after a JWT's limit (403) and the crossing call completes. The run's spend is the sum of every
    # JWT's spending_current, so there are still no per-Agent budgets.

    def __init__(self, admin_key, cap, ttl):
        self.admin_key, self.cap, self.ttl = admin_key, cap, ttl
        self.tokens = {}  # jwt -> last read spending_current

    def mint(self, model):
        remaining = round(self.cap - self.spent_known(), 6)
        if remaining <= 0:
            raise BudgetExhausted(f"${self.spent_known():.4f} spent against a ${self.cap:.2f} cap")
        status, r = http_client.request("POST", f"{provider.DEEPINFRA}/v1/scoped-jwt", self.admin_key,
                         {"api_key_name": "auto", "models": [model], "expires_delta": self.ttl, "spending_limit": remaining})
        if status == 402:
            raise ProviderBlocked(provider.BLOCKED_MESSAGE)
        if status != 200 or "token" not in r:
            raise RuntimeError(f"could not mint scoped JWT: HTTP {status} {r}")
        print(f"::add-mask::{r['token']}", flush=True)
        self.tokens[r["token"]] = 0.0
        return r["token"]

    def spent_known(self):
        return sum(self.tokens.values())

    def refresh(self, jwt):
        status, r = http_client.request("GET", f"{provider.DEEPINFRA}/v1/scoped-jwt?jwtoken={jwt}", self.admin_key)
        if status != 200:
            raise RuntimeError(f"could not read JWT spend: HTTP {status}")
        self.tokens[jwt] = float(r["spending_current"])
        return self.spent_known()
