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
    return any(BLOCKED_LINE_RE.search(line) and BLOCKED_EVENT_RE.search(line) for line in (text or "").splitlines())


SPENDING_LIMIT_RE = re.compile(r"token spending limit exceeded", re.I)


def spending_limit_hit(path, tail_bytes=300_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            return bool(SPENDING_LIMIT_RE.search(f.read().decode(errors="replace")))
    except OSError:
        return False


def scan_for_provider_block(path, tail_bytes=300_000):
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
    status, r = http_client.request("POST", f"{base_url}/chat/completions", key,
                     {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}, timeout=30)
    if status == 402 or (status == 400 and provider_blocked_text(f"BadRequestError {r}")):
        raise ProviderBlocked(BLOCKED_MESSAGE)
