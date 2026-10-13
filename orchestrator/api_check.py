#!/usr/bin/env python3
"""api-check: the tester states what a request should return; this observes what it does return and compares them.

The tester agent used to run `curl` and judge for itself whether the answer was right, and the seeded-bug benchmark
(agents/smoke-tester) showed that judgement slipping: a 200 where the spec says 201 was waved through. Here the model's
job is only to say *which* checks the spec calls for and what each expects. The comparison is mechanical, and every result
is appended to a log (`$API_CHECK_LOG`) that the Orchestrator reads, so a failure the helper saw cannot be reported as a
pass, or left out of the report (build_run.reconcile_api_checks).

  python3 api_check.py checks.json [--base https://app.fly.dev]

Env: PREVIEW_TOKEN (sent as X-Preview-Token for a check with "auth": "preview"; never printed or logged),
API_CHECK_BASE (the base URL if --base is not given), API_CHECK_LOG (a JSONL file each result is appended to).
Exit status 0 if every check passed, 1 if any failed, 2 if the file is unusable. Standard library only.

A checks file is {"checks": [...]} (or the list itself). Each check:

  {"id": "create-201",                         unique; the report refers to it
   "name": "POST /api/notes with valid text answers 201",
   "request": {"method": "POST", "path": "/api/notes", "auth": "preview" | "none",
               "json": {"text": "a"}  or  "body": "raw text, e.g. malformed JSON",  "headers": {"X-Other": "v"}},
   "expect": {"status": 201 | [200, 201],
              "json": {"id": "<integer>", "text": "a"},     a subset match: extra keys in the answer are fine, lists must
                                                            be the same length, and "<number>", "<integer>", "<string>",
                                                            "<nonempty-string>", "<boolean>", "<array>", "<object>",
                                                            "<null>" and "<any>" stand for any value of that kind
              "body_contains": ["..."], "body_not_contains": ["..."],
              "headers": {"content-type": "application/json"}, "header_absent": ["x-secret"]},
   "capture": {"note_id": "id"}}               remember a value from the answer (dotted path, e.g. "items.0.id") and use
                                               it as {note_id} in later paths and JSON

Checks run in order, one request each, 15 seconds at most per request, at most 100 per file, and only against the base URL.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

MAX_CHECKS = 100
TIMEOUT = 15
BODY_LIMIT = 2000

TYPES = {
    "<number>": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "<integer>": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "<string>": lambda v: isinstance(v, str),
    "<nonempty-string>": lambda v: isinstance(v, str) and v.strip() != "",
    "<boolean>": lambda v: isinstance(v, bool),
    "<array>": lambda v: isinstance(v, list),
    "<object>": lambda v: isinstance(v, dict),
    "<null>": lambda v: v is None,
    "<any>": lambda v: True,
}


# --- pure logic (unit-tested) -------------------------------------------------


def mismatches(expected, observed, path="$"):
    """What differs between an expectation and an observed JSON value; an empty list means it matches."""
    if isinstance(expected, str) and expected in TYPES:
        return [] if TYPES[expected](observed) else [f"{path}: expected {expected[1:-1]}, got {short(observed)}"]
    if isinstance(expected, dict):
        if not isinstance(observed, dict):
            return [f"{path}: expected an object, got {short(observed)}"]
        out = []
        for key, want in expected.items():
            if key not in observed:
                out.append(f"{path}.{key}: missing")
            else:
                out += mismatches(want, observed[key], f"{path}.{key}")
        return out
    if isinstance(expected, list):
        if not isinstance(observed, list):
            return [f"{path}: expected an array, got {short(observed)}"]
        if len(expected) != len(observed):
            return [f"{path}: expected {len(expected)} item(s), got {len(observed)}"]
        out = []
        for i, (want, got) in enumerate(zip(expected, observed)):
            out += mismatches(want, got, f"{path}[{i}]")
        return out
    if isinstance(expected, bool) or isinstance(observed, bool):
        return [] if expected is observed else [f"{path}: expected {short(expected)}, got {short(observed)}"]
    return [] if expected == observed else [f"{path}: expected {short(expected)}, got {short(observed)}"]


def short(value, n=80):
    text = json.dumps(value) if not isinstance(value, str) else repr(value)
    return text if len(text) <= n else text[: n - 3] + "..."


def dig(value, dotted):
    """The value at a dotted path ('items.0.id'), or raises KeyError."""
    for part in str(dotted).split("."):
        if isinstance(value, list):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(part)
    return value


def substitute(value, captures):
    """{name} replaced by a captured value in a string or inside nested JSON; unknown names are left as they are."""
    if isinstance(value, str):
        return re.sub(r"\{([A-Za-z_]\w*)\}", lambda m: str(captures[m.group(1)]) if m.group(1) in captures else m.group(0), value)
    if isinstance(value, dict):
        return {k: substitute(v, captures) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, captures) for v in value]
    return value


def compare(expect, status, body_text, body_json, headers):
    """The problems found when an answer is held against `expect` (empty list: the check passed)."""
    problems = []
    if "status" in expect:
        want = expect["status"] if isinstance(expect["status"], list) else [expect["status"]]
        if status not in want:
            problems.append(f"status: expected {' or '.join(str(w) for w in want)}, got {status}")
    if "json" in expect:
        if body_json is None:
            problems.append("json: the answer is not JSON")
        else:
            problems += mismatches(expect["json"], body_json)
    for needle in expect.get("body_contains", []):
        if needle not in body_text:
            problems.append(f"body does not contain {short(needle)}")
    for needle in expect.get("body_not_contains", []):
        if needle in body_text:
            problems.append(f"body contains {short(needle)}, which it must not")
    lowered = {k.lower(): v for k, v in headers.items()}
    for name, want in expect.get("headers", {}).items():
        got = lowered.get(name.lower())
        if got is None or want.lower() not in got.lower():
            problems.append(f"header {name}: expected {short(want)}, got {short(got)}")
    for name in expect.get("header_absent", []):
        if name.lower() in lowered:
            problems.append(f"header {name} is present, and must not be")
    return problems


def validate(doc):
    """(checks, error). The file must be a list of checks (or {"checks": [...]}) with unique ids."""
    checks = doc.get("checks") if isinstance(doc, dict) else doc
    if not isinstance(checks, list) or not checks:
        return None, "the file needs a non-empty list of checks"
    if len(checks) > MAX_CHECKS:
        return None, f"at most {MAX_CHECKS} checks per file"
    seen = set()
    for i, c in enumerate(checks):
        if not isinstance(c, dict) or not isinstance(c.get("request"), dict) or not isinstance(c.get("expect"), dict):
            return None, f"check {i + 1} needs a `request` and an `expect`"
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip() or cid in seen:
            return None, f"check {i + 1} needs a unique string `id`"
        seen.add(cid)
        path = c["request"].get("path", "")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "://" in path:
            return None, f"check {cid}: `path` must start with a single / (only the base URL is ever called)"
        if not c["expect"]:
            return None, f"check {cid}: `expect` is empty, so nothing would be checked"
    return checks, None


# --- running (network) ----------------------------------------------------------


def do_request(base, request, captures, token):
    """(status, body text, parsed JSON or None, headers, error). A connection failure is status 0 with an error."""
    method = str(request.get("method", "GET")).upper()
    url = base.rstrip("/") + substitute(request["path"], captures)
    headers = {k: str(substitute(v, captures)) for k, v in (request.get("headers") or {}).items()}
    data = None
    if "json" in request:
        data = json.dumps(substitute(request["json"], captures)).encode()
        headers.setdefault("Content-Type", "application/json")
    elif "body" in request:
        data = str(substitute(request["body"], captures)).encode()
        headers.setdefault("Content-Type", "application/json")
    if request.get("auth") == "preview":
        if not token:
            return 0, "", None, {}, "PREVIEW_TOKEN is not set in the environment, so an auth: preview check cannot be made"
        headers["X-Preview-Token"] = token
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, raw, hdrs = r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), dict(e.headers)
    except (urllib.error.URLError, OSError) as e:
        return 0, "", None, {}, f"could not reach {url}: {e}"
    text = raw.decode(errors="replace")
    try:
        parsed = json.loads(text) if text.strip() else None
    except ValueError:
        parsed = None
    return status, text, parsed, hdrs, None


def run_checks(checks, base, token, log_path=None):
    """Run the checks in order. Returns the result dicts; appends each to `log_path` as one JSON line."""
    captures, results = {}, []
    for c in checks:
        began = time.time()
        status, text, parsed, headers, error = do_request(base, c["request"], captures, token)
        problems = [error] if error else compare(c["expect"], status, text, parsed, headers)
        for name, dotted in (c.get("capture") or {}).items():
            try:
                captures[name] = dig(parsed, dotted)
            except (KeyError, IndexError, ValueError, TypeError):
                problems.append(f"capture {name}: nothing at {dotted!r} in the answer")
        body = text if len(text) <= BODY_LIMIT else text[:BODY_LIMIT] + "..."
        if token:
            body = body.replace(token, "[TOKEN]")
        results.append({"id": c["id"], "name": c.get("name") or c["id"], "ok": not problems, "problems": problems,
                        "expected": c["expect"], "observed": {"status": status, "body": body}, "ms": round((time.time() - began) * 1000)})
        if log_path:
            with open(log_path, "a") as f:
                f.write(json.dumps(results[-1]) + "\n")
    return results


def render(results):
    lines = []
    for r in results:
        if r["ok"]:
            lines.append(f"PASS {r['id']}: {r['name']}")
        else:
            lines.append(f"FAIL {r['id']}: {r['name']}\n     " + "; ".join(r["problems"])
                         + f"\n     observed: status {r['observed']['status']}, body {r['observed']['body'][:200]!r}")
    failed = sum(not r["ok"] for r in results)
    lines.append(f"{len(results) - failed} passed, {failed} failed")
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    base = os.environ.get("API_CHECK_BASE", "")
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]
        args = [a for a in args if a != base]
    if len(args) != 1 or not base.startswith(("http://", "https://")):
        print("usage: api_check.py checks.json --base https://host   (or set API_CHECK_BASE)", file=sys.stderr)
        return 2
    try:
        with open(args[0]) as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read {args[0]}: {e}", file=sys.stderr)
        return 2
    checks, error = validate(doc)
    if error:
        print(f"unusable checks file: {error}", file=sys.stderr)
        return 2
    results = run_checks(checks, base, os.environ.get("PREVIEW_TOKEN"), os.environ.get("API_CHECK_LOG"))
    print(render(results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
