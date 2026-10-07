#!/usr/bin/env python3
"""Experiment for #35: does GET /v1/scoped-jwt report spending_current accurately and promptly,
and what happens when a JWT's spending_limit is crossed? Prints numbers only, never a key."""
import json, os, time, urllib.request, urllib.error

BASE = "https://api.deepinfra.com"
ADMIN = os.environ["DEEPINFRA_API_KEY"]
MODEL = "deepseek-ai/DeepSeek-V4-Pro-0813"

def call(method, path, body=None, key=None, query=""):
    req = urllib.request.Request(f"{BASE}{path}{query}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key or ADMIN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode(errors="replace")

def mint(limit):
    s, r = call("POST", "/v1/scoped-jwt", {"api_key_name": "auto", "models": [MODEL],
                                           "expires_delta": 900, "spending_limit": limit})
    assert s == 200, (s, r)
    return r["token"]

def inspect(jwt):
    s, r = call("GET", "/v1/scoped-jwt", query=f"?jwtoken={jwt}")
    return r.get("spending_current") if s == 200 else f"HTTP {s}"

def chat(jwt, n):
    return call("POST", "/v1/openai/chat/completions", {"model": MODEL, "max_tokens": 200,
        "messages": [{"role": "user", "content": f"Write {n} sentences about rivers."}]}, key=jwt)

print("== A: accuracy and freshness (limit $0.05)")
jwt = mint(0.05)
print("initial spending_current:", inspect(jwt))
total = 0.0
for i, n in enumerate([3, 10, 25, 5, 40], 1):
    s, r = chat(jwt, n)
    cost = r["usage"]["estimated_cost"] if s == 200 else None
    total += cost or 0
    now = inspect(jwt)
    time.sleep(5)
    later = inspect(jwt)
    print(f"call {i}: HTTP {s} estimated_cost={cost} sum={total:.6f} | spending_current immediately={now} after 5s={later}")

print("== B: breach behavior (limit $0.0004)")
jwt = mint(0.0004)
for i in range(1, 15):
    s, r = chat(jwt, 20)
    cost = r["usage"]["estimated_cost"] if s == 200 else None
    print(f"call {i}: HTTP {s} estimated_cost={cost} spending_current={inspect(jwt)}" + ("" if s == 200 else f" body={str(r)[:140]!r}"))
    if s != 200:
        break
