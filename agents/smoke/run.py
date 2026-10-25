#!/usr/bin/env python3
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("MODEL", "deepseek-ai/DeepSeek-V4-Pro-0813")
BASE = "https://api.deepinfra.com/v1/openai"
KEY = os.environ["DEEPINFRA_API_KEY"]
TRIALS = int(os.environ.get("TRIALS", "3"))
WORKERS = int(os.environ.get("WORKERS", "6"))
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "")
HERE = pathlib.Path(__file__).parent

sys.path.insert(0, str(HERE.parent.parent / "orchestrator"))
from build_run import review_code  # noqa: E402
from shared import prompts  # noqa: E402

VERDICT_SCHEMA = review_code.REVIEW_SCHEMA
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "review_verdict", "schema": VERDICT_SCHEMA, "strict": True},
}

def review_system():
    return prompts.render(
        prompts.load_prompt("prompts/reviewer-fast.md"),
        {"app_name": "smoke-app", "base_sha": "base", "head_sha": "head"})

TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file from the repository",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
}]

results = []
def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}", flush=True)

def chat(payload, attempts=5):
    extra = {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}
    body = json.dumps({"model": MODEL, **extra, **payload}).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", data=body, headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
            if (e.code == 429 or e.code >= 500) and attempt < attempts:
                time.sleep(10 * attempt)
                continue
            raise RuntimeError(detail)
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt == attempts:
                raise RuntimeError(f"{type(e).__name__}: {e}")
            time.sleep(10 * attempt)

def message(resp):
    return resp["choices"][0]["message"]

def parse_verdict(resp):
    text = message(resp).get("content") or ""
    v = json.loads(text)
    v["model_verdict"] = v["verdict"]
    v["findings"] = review_code.banded_findings(v)
    v["verdict"] = "changes_requested" if any(f["severity"] == "blocking" for f in v["findings"]) else "clean"
    return v

try:
    r = chat({"max_tokens": 5, "messages": [{"role": "user", "content": "Say hi."}]})
    cost = r.get("usage", {}).get("estimated_cost")
    record("T1 usage.estimated_cost present", cost is not None, f"(value={cost}, usage keys={sorted(r.get('usage', {}))})")
except Exception as e:
    record("T1 usage.estimated_cost present", False, f"({e})")

try:
    msgs = [{"role": "user", "content": "Use read_file to read src/a.ts, then tell me in one sentence what it exports."}]
    r1 = chat({"messages": msgs, "tools": TOOLS, "tool_choice": "auto"})
    m1 = message(r1)
    calls = m1.get("tool_calls") or []
    has_reasoning = bool(m1.get("reasoning_content") or m1.get("reasoning"))
    if not calls:
        record("T2 tool call round-trip", False, "(model did not call the tool)")
    else:
        msgs.append(m1)
        msgs.append({"role": "tool", "tool_call_id": calls[0]["id"], "content": "export const answer = 42;"})
        r2 = chat({"messages": msgs, "tools": TOOLS})
        final = message(r2).get("content") or ""
        record("T2 tool call round-trip", "answer" in final.lower(), f"(emits reasoning={has_reasoning}; final mentions export={'answer' in final.lower()})")
except Exception as e:
    record("T2 tool call round-trip", False, f"({e})")

def load_fixture(p):
    intake = p.with_suffix(".intake.md")
    prefix = f"Contents of INTAKE.md:\n{intake.read_text()}\n\n" if intake.exists() else ""
    return prefix + p.read_text()

ONLY = {n for n in os.environ.get("FIXTURES", "").split(",") if n}
fixtures = {p.stem: load_fixture(p) for p in sorted((HERE / "fixtures").glob("*.diff")) if not ONLY or p.stem in ONLY}
expected = json.loads((HERE / "expected.json").read_text())

def review(diff, extra=None):
    return chat({"messages": [{"role": "system", "content": review_system()},
                              {"role": "user", "content": f"Review this diff:\n\n{diff}"}],
                 "response_format": RESPONSE_FORMAT, **(extra or {})})

try:
    v = parse_verdict(review(fixtures["clean"]))
    record("T3 schema-valid structured output", v["verdict"] in ("clean", "changes_requested") and isinstance(v["findings"], list))
except Exception as e:
    record("T3 schema-valid structured output", False, f"({e})")

try:
    r = review(fixtures["clean"], {"tools": TOOLS, "tool_choice": "auto"})
    m = message(r)
    ok = bool(m.get("tool_calls")) or bool(json.loads(m.get("content") or "null"))
    record("T4 structured output + tools together", ok, f"(tool_calls={bool(m.get('tool_calls'))})")
except Exception as e:
    record("T4 structured output + tools together", False, f"({e})")

def grade(want, v):
    if v["verdict"] != want["verdict"]:
        return False
    if want["verdict"] == "changes_requested":
        blob = " ".join(f["summary"] + " " + f["evidence"] for f in v["findings"] if f["severity"] == "blocking")
        if not re.search(want["match"], blob, re.I):
            return False
    if want.get("no_finding_match"):
        blob = " ".join(f["summary"] + " " + f["evidence"] for f in v["findings"])
        if re.search(want["no_finding_match"], blob, re.I):
            return False
    if want.get("minor_match"):
        blob = " ".join(f["summary"] + " " + f["evidence"] for f in v["findings"] if f["severity"] == "minor")
        if not re.search(want["minor_match"], blob, re.I):
            return False
    return True

def trial(name):
    start = time.time()
    try:
        r = review(fixtures[name])
        v = parse_verdict(r)
        u = r.get("usage", {})
        return {"name": name, "ok": grade(expected[name], v), "v": v, "secs": time.time() - start,
                "cost": u.get("estimated_cost") or 0, "tokens": u.get("completion_tokens") or 0}
    except Exception as e:
        return {"name": name, "error": str(e)}

jobs = [name for name in fixtures for _ in range(TRIALS)]
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    outcomes = list(pool.map(trial, jobs))

total_cost = 0.0
for name in fixtures:
    rows = [o for o in outcomes if o["name"] == name]
    good = [o for o in rows if "error" not in o]
    for o in rows:
        if "error" in o:
            print(f"      trial error on {name}: {o['error']}", flush=True)
        else:
            v = o["v"]
            print(f"      {name}: verdict={v['verdict']} (model said {v['model_verdict']}) findings={[f['severity'] for f in v['findings']]} "
                  f"first={(v['findings'][0]['summary'][:90] if v['findings'] else '-')!r}", flush=True)
    total_cost += sum(o["cost"] for o in good)
    passed = sum(o["ok"] for o in good)
    stats = (f"; avg {sum(o['secs'] for o in good) / len(good):.0f}s, {sum(o['tokens'] for o in good) // len(good)} output tokens"
             if good else "")
    errors = len(rows) - len(good)
    record(f"T5 fixture {name}", bool(good) and passed >= max(1, len(good) - 1),
           f"({passed}/{len(good)} trials correct{f', {errors} errored' if errors else ''}{stats})")

print(f"\nModel {MODEL}, reasoning_effort={REASONING_EFFORT or 'default'}")
print(f"Total estimated cost of T5 calls: ${total_cost:.4f}")
failed = [n for n, ok, _ in results if not ok]
pathlib.Path("smoke-results.json").write_text(json.dumps(
    [{"name": n, "ok": ok, "detail": d} for n, ok, d in results], indent=2), encoding="utf-8")
sys.exit(1 if failed else 0)
