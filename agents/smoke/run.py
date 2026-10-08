#!/usr/bin/env python3
"""Smoke test for the reviewer model (issue #33).

Checks, against DeepInfra's OpenAI-compatible API, that the model:
  T1 returns usage.estimated_cost (the cost guardrail depends on it)
  T2 round-trips a tool call (incl. reasoning_content if the model emits it)
  T3 produces schema-valid structured JSON
  T4 does structured output and tools in the same request
  T5 finds known bugs / passes a clean diff (agents/smoke/fixtures), N trials each

Prints pass/fail only. The key comes from DEEPINFRA_API_KEY and is never printed.
"""
import json, os, re, sys, time, urllib.request, urllib.error, pathlib

MODEL = os.environ.get("MODEL", "deepseek-ai/DeepSeek-V4-Pro-0813")
BASE = "https://api.deepinfra.com/v1/openai"
KEY = os.environ["DEEPINFRA_API_KEY"]
TRIALS = int(os.environ.get("TRIALS", "3"))
HERE = pathlib.Path(__file__).parent

# Property order matters: generation follows it, so the model must write its
# analysis and findings BEFORE it commits to a verdict. (A first attempt with
# `verdict` first approved every diff, including an obvious command injection.)
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["blocking", "minor"]},
                    "summary": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["severity", "summary", "evidence"],
                "additionalProperties": False,
            },
        },
        "verdict": {"type": "string", "enum": ["clean", "changes_requested"]},
    },
    "required": ["analysis", "findings", "verdict"],
    "additionalProperties": False,
}
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "review_verdict", "schema": VERDICT_SCHEMA, "strict": True},
}
# The real reviewer prompt, with its placeholders filled for a direct API call:
# the diff is in the message and the verdict is the reply, not a file.
REVIEW_SYSTEM = (
    (HERE.parent / "prompts" / "reviewer.md").read_text()
    .replace("{{app_name}}", "smoke-app")
    .replace("`{{base_sha}}..{{head_sha}}` (`git log` and `git diff` show them)", "in the diff you are given")
    .replace("`{{verdict_path}}`", "your reply")
    + "\nReply with the JSON object only."
)

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
    """One API call. Retries overload (429), server errors (5xx) and timeouts with backoff:
    those say nothing about the model, and counting them as wrong verdicts made a busy
    provider look like a regression."""
    body = json.dumps({"model": MODEL, **payload}).encode()
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
    # The Orchestrator derives the verdict from the findings instead of
    # trusting the model's own field.
    v["model_verdict"] = v["verdict"]
    v["verdict"] = "changes_requested" if any(f["severity"] == "blocking" for f in v["findings"]) else "clean"
    return v

# T1
try:
    r = chat({"max_tokens": 5, "messages": [{"role": "user", "content": "Say hi."}]})
    cost = r.get("usage", {}).get("estimated_cost")
    record("T1 usage.estimated_cost present", cost is not None, f"(value={cost}, usage keys={sorted(r.get('usage', {}))})")
except Exception as e:
    record("T1 usage.estimated_cost present", False, f"({e})")

# T2
try:
    msgs = [{"role": "user", "content": "Use read_file to read src/a.ts, then tell me in one sentence what it exports."}]
    r1 = chat({"messages": msgs, "tools": TOOLS, "tool_choice": "auto"})
    m1 = message(r1)
    calls = m1.get("tool_calls") or []
    has_reasoning = bool(m1.get("reasoning_content") or m1.get("reasoning"))
    if not calls:
        record("T2 tool call round-trip", False, "(model did not call the tool)")
    else:
        msgs.append(m1)  # replay exactly as returned, incl. reasoning_content if present
        msgs.append({"role": "tool", "tool_call_id": calls[0]["id"], "content": "export const answer = 42;"})
        r2 = chat({"messages": msgs, "tools": TOOLS})
        final = message(r2).get("content") or ""
        record("T2 tool call round-trip", "answer" in final.lower(), f"(emits reasoning={has_reasoning}; final mentions export={'answer' in final.lower()})")
except Exception as e:
    record("T2 tool call round-trip", False, f"({e})")

def load_fixture(p):
    # An optional <name>.intake.md stands in for the repo's INTAKE.md, which the real reviewer reads.
    intake = p.with_suffix(".intake.md")
    prefix = f"Contents of INTAKE.md:\n{intake.read_text()}\n\n" if intake.exists() else ""
    return prefix + p.read_text()

fixtures = {p.stem: load_fixture(p) for p in sorted((HERE / "fixtures").glob("*.diff"))}
expected = json.loads((HERE / "expected.json").read_text())

def review(diff, extra=None):
    return chat({"messages": [{"role": "system", "content": REVIEW_SYSTEM},
                              {"role": "user", "content": f"Review this diff:\n\n{diff}"}],
                 "response_format": RESPONSE_FORMAT, **(extra or {})})

# T3
try:
    v = parse_verdict(review(fixtures["clean"]))
    record("T3 schema-valid structured output", v["verdict"] in ("clean", "changes_requested") and isinstance(v["findings"], list))
except Exception as e:
    record("T3 schema-valid structured output", False, f"({e})")

# T4
try:
    r = review(fixtures["clean"], {"tools": TOOLS, "tool_choice": "auto"})
    m = message(r)
    ok = bool(m.get("tool_calls")) or bool(json.loads(m.get("content") or "null"))
    record("T4 structured output + tools together", ok, f"(tool_calls={bool(m.get('tool_calls'))})")
except Exception as e:
    record("T4 structured output + tools together", False, f"({e})")

# T5
total_cost = 0.0
for name, diff in fixtures.items():
    want = expected[name]
    passed = 0
    for _ in range(TRIALS):
        try:
            r = review(diff)
            total_cost += r.get("usage", {}).get("estimated_cost") or 0
            v = parse_verdict(r)
            sev = [f["severity"] for f in v["findings"]]
            print(f"      {name}: verdict={v['verdict']} (model said {v['model_verdict']}) findings={sev} "
                  f"first={(v['findings'][0]['summary'][:90] if v['findings'] else '-')!r}", flush=True)
            if v["verdict"] != want["verdict"]:
                continue
            if want["verdict"] == "changes_requested":
                blob = " ".join(f["summary"] + " " + f["evidence"] for f in v["findings"] if f["severity"] == "blocking")
                if not re.search(want["match"], blob, re.I):
                    continue
            if want.get("no_finding_match"):
                blob = " ".join(f["summary"] + " " + f["evidence"] for f in v["findings"])
                if re.search(want["no_finding_match"], blob, re.I):
                    continue
            if want.get("minor_match"):
                blob = " ".join(f["summary"] + " " + f["evidence"] for f in v["findings"] if f["severity"] == "minor")
                if not re.search(want["minor_match"], blob, re.I):
                    continue
            passed += 1
        except Exception as e:
            print(f"      trial error on {name}: {e}", flush=True)
    record(f"T5 fixture {name}", passed >= max(1, TRIALS - 1), f"({passed}/{TRIALS} trials correct)")

print(f"\nTotal estimated cost of T5 calls: ${total_cost:.4f}")
failed = [n for n, ok, _ in results if not ok]
pathlib.Path("smoke-results.json").write_text(json.dumps(
    [{"name": n, "ok": ok, "detail": d} for n, ok, d in results], indent=2))
sys.exit(1 if failed else 0)
