# The model provider (DeepInfra): its address, how its refusals look, and the checks made before a run spends anything.
import re

from shared import http_client
from shared.run_stops import ProviderBlocked

DEEPINFRA = "https://api.deepinfra.com"


BLOCKED_MESSAGE = ("The model provider refused the request because the account has no balance (HTTP 402, \"You need positive balance to "
                   "do inference\"). Add balance (or turn on auto top-up) in the provider's dashboard, then add `proceed-with-change` "
                   "again to retry.")


BLOCKED_LINE_RE = re.compile(r"positive balance|insufficient (funds|balance|credits?)|payment required", re.I)


BLOCKED_EVENT_RE = re.compile(r"BadRequestError|ConversationErrorEvent|LLMError|\b402\b")


def provider_blocked_text(text):
    # True if some line of an Agent's output is an error from the provider saying the account has no balance. Both parts
    # are needed on one line (an error event and the billing wording), so a prompt or a log that merely mentions balances
    # does not trip it.
    return any(BLOCKED_LINE_RE.search(line) and BLOCKED_EVENT_RE.search(line) for line in (text or "").splitlines())


SPENDING_LIMIT_RE = re.compile(r"token spending limit exceeded", re.I)


def spending_limit_hit(path, tail_bytes=300_000):
    # True when the end of an Agent's JSONL output shows its own scoped credential ran out (the provider's "token spending limit exceeded"),
    # which is the credential's cap, not an empty account (that is `scan_for_provider_block`).
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            return bool(SPENDING_LIMIT_RE.search(f.read().decode(errors="replace")))
    except OSError:
        return False


def scan_for_provider_block(path, tail_bytes=300_000):
    # BLOCKED_MESSAGE if the end of an Agent's JSONL output shows the provider refusing for lack of balance, else None.
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            text = f.read().decode(errors="replace")
    except OSError:
        return None
    return BLOCKED_MESSAGE if provider_blocked_text(text) else None


MODEL_MISSING_RE = re.compile(r"(?i)model[^\"]{0,60}(not found|does not exist|not available|unknown|invalid|deprecated|unsupported|no longer)")


def model_status(base_url, key, model):
    # 'ok', 'missing' (the provider no longer serves this model id) or 'unknown' (any other answer, left for the run to deal with), from a one-token
    # request. Raises ProviderBlocked when the account has no balance, exactly like provider_check.
    status, r = http_client.request("POST", f"{base_url}/chat/completions", key,
                     {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}, timeout=30)
    if status == 402 or (status == 400 and provider_blocked_text(f"BadRequestError {r}")):
        raise ProviderBlocked(BLOCKED_MESSAGE)
    if status == 200:
        return "ok"
    if status == 404 or (status in (400, 422) and MODEL_MISSING_RE.search(str(r))):
        return "missing"
    return "unknown"


def provider_check(base_url, key, model):
    # A one-token request before a Build Run does any work: raises ProviderBlocked if the account has no balance, so a run
    # cannot spend a clone, a checkout and a planner call to find out. Any other answer (including an outage) is not this
    # condition and is left for the run to deal with.
    status, r = http_client.request("POST", f"{base_url}/chat/completions", key,
                     {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}, timeout=30)
    if status == 402 or (status == 400 and provider_blocked_text(f"BadRequestError {r}")):
        raise ProviderBlocked(BLOCKED_MESSAGE)
