#!/usr/bin/env python3
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
CREDENTIAL_STATUSES = {401, 403}

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


def object_mismatches(expected, observed, path):
    if not isinstance(observed, dict):
        return [f"{path}: expected an object, got {short(observed)}"]
    out = []
    for key, want in expected.items():
        out += mismatches(want, observed[key], f"{path}.{key}") if key in observed else [f"{path}.{key}: missing"]
    return out


def array_mismatches(expected, observed, path):
    if not isinstance(observed, list):
        return [f"{path}: expected an array, got {short(observed)}"]
    if len(expected) != len(observed):
        return [f"{path}: expected {len(expected)} item(s), got {len(observed)}"]
    return [m for i, (want, got) in enumerate(zip(expected, observed)) for m in mismatches(want, got, f"{path}[{i}]")]


def mismatches(expected, observed, path="$"):
    if isinstance(expected, str) and expected in TYPES:
        return [] if TYPES[expected](observed) else [f"{path}: expected {expected[1:-1]}, got {short(observed)}"]
    if isinstance(expected, dict):
        return object_mismatches(expected, observed, path)
    if isinstance(expected, list):
        return array_mismatches(expected, observed, path)
    if isinstance(expected, bool) or isinstance(observed, bool):
        return [] if expected is observed else [f"{path}: expected {short(expected)}, got {short(observed)}"]
    return [] if expected == observed else [f"{path}: expected {short(expected)}, got {short(observed)}"]


def short(value, n=80):
    text = json.dumps(value) if not isinstance(value, str) else repr(value)
    return text if len(text) <= n else text[: n - 3] + "..."


def dig(value, dotted):
    for part in str(dotted).split("."):
        if isinstance(value, list):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(part)
    return value


def substitute(value, captures):
    if isinstance(value, str):
        return re.sub(r"\{([A-Za-z_]\w*)\}", lambda m: str(captures[m.group(1)]) if m.group(1) in captures else m.group(0), value)
    if isinstance(value, dict):
        return {k: substitute(v, captures) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, captures) for v in value]
    return value


def expected_statuses(expect):
    want = expect.get("status", [])
    return want if isinstance(want, list) else [want]


def status_problems(expect, status):
    if "status" not in expect:
        return []
    want = expected_statuses(expect)
    return [] if status in want else [f"status: expected {' or '.join(str(w) for w in want)}, got {status}"]


def json_problems(expect, body_json):
    if "json" not in expect:
        return []
    return mismatches(expect["json"], body_json) if body_json is not None else ["json: the answer is not JSON"]


def body_problems(expect, body_text):
    missing = [f"body does not contain {short(n)}" for n in expect.get("body_contains", []) if n not in body_text]
    return missing + [f"body contains {short(n)}, which it must not" for n in expect.get("body_not_contains", []) if n in body_text]


def header_problems(expect, headers):
    lowered = {k.lower(): v for k, v in headers.items()}
    wrong = [(name, want, lowered.get(name.lower())) for name, want in expect.get("headers", {}).items()]
    problems = [f"header {name}: expected {short(want)}, got {short(got)}" for name, want, got in wrong if got is None or want.lower() not in got.lower()]
    return problems + [f"header {name} is present, and must not be" for name in expect.get("header_absent", []) if name.lower() in lowered]


def refused_for_credential(expect, status):
    return status in CREDENTIAL_STATUSES and not CREDENTIAL_STATUSES.intersection(expected_statuses(expect))


def result_state(result):
    if result["ok"]:
        return "passed"
    return "blocked" if result.get("blocked") else "failed"


def compare(expect, status, body_text, body_json, headers):
    return status_problems(expect, status) + json_problems(expect, body_json) + body_problems(expect, body_text) + header_problems(expect, headers)


def validate(doc):
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


def request_body(request, captures, headers):
    if "json" in request:
        headers.setdefault("Content-Type", "application/json")
        return json.dumps(substitute(request["json"], captures)).encode()
    if "body" in request:
        headers.setdefault("Content-Type", "application/json")
        return str(substitute(request["body"], captures)).encode()
    return None


def send(req, url):
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(), dict(r.headers), None
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers), None
    except (urllib.error.URLError, OSError) as e:
        return 0, b"", {}, f"could not reach {url}: {e}"


def parse_json(text):
    try:
        return json.loads(text) if text.strip() else None
    except ValueError:
        return None


def do_request(base, request, captures, token):
    url = base.rstrip("/") + substitute(request["path"], captures)
    headers = {k: str(substitute(v, captures)) for k, v in (request.get("headers") or {}).items()}
    data = request_body(request, captures, headers)
    if request.get("auth") == "preview":
        if not token:
            return 0, "", None, {}, "PREVIEW_TOKEN is not set in the environment, so an auth: preview check cannot be made"
        headers["X-Preview-Token"] = token
    status, raw, hdrs, problem = send(urllib.request.Request(url, data=data, method=str(request.get("method", "GET")).upper(), headers=headers), url)
    if problem:
        return 0, "", None, {}, problem
    text = raw.decode(errors="replace")
    return status, text, parse_json(text), hdrs, None


def capture_problems(captures, c, parsed):
    problems = []
    for name, dotted in (c.get("capture") or {}).items():
        try:
            captures[name] = dig(parsed, dotted)
        except (KeyError, IndexError, ValueError, TypeError):
            problems.append(f"capture {name}: nothing at {dotted!r} in the answer")
    return problems


def check_record(c, observed, problems, began, token):
    status, text = observed
    body = text if len(text) <= BODY_LIMIT else text[:BODY_LIMIT] + "..."
    return {"id": c["id"], "name": c.get("name") or c["id"], "ok": not problems, "blocked": bool(problems) and refused_for_credential(c["expect"], status),
            "problems": problems, "expected": c["expect"], "observed": {"status": status, "body": body.replace(token, "[TOKEN]") if token else body},
            "ms": round((time.time() - began) * 1000)}


def run_checks(checks, base, token, log_path=None):
    captures, results = {}, []
    for c in checks:
        began = time.time()
        status, text, parsed, headers, error = do_request(base, c["request"], captures, token)
        problems = [error] if error else compare(c["expect"], status, text, parsed, headers)
        results.append(check_record(c, (status, text), problems + capture_problems(captures, c, parsed), began, token))
        if log_path:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(results[-1]) + "\n")
    return results


def render_line(r):
    if r["ok"]:
        return f"PASS {r['id']}: {r['name']}"
    label = "BLOCKED" if result_state(r) == "blocked" else "FAIL"
    return (f"{label} {r['id']}: {r['name']}\n     " + "; ".join(r["problems"])
            + f"\n     observed: status {r['observed']['status']}, body {r['observed']['body'][:200]!r}")


def render(results):
    states = [result_state(r) for r in results]
    summary = f"{states.count('passed')} passed, {states.count('failed')} failed, {states.count('blocked')} blocked"
    note = ["blocked: the app refused a credential this tester does not hold, so the live app cannot answer the check"] if "blocked" in states else []
    return "\n".join([render_line(r) for r in results] + [summary] + note)


def read_args(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    base = os.environ.get("API_CHECK_BASE", "")
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]
        args = [a for a in args if a != base]
    return args, base


def load_checks(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read {path}: {e}", file=sys.stderr)
        return None
    checks, error = validate(doc)
    if error:
        print(f"unusable checks file: {error}", file=sys.stderr)
    return checks


def main(argv):
    args, base = read_args(argv)
    if len(args) != 1 or not base.startswith(("http://", "https://")):
        print("usage: api_check.py checks.json --base https://host   (or set API_CHECK_BASE)", file=sys.stderr)
        return 2
    checks = load_checks(args[0])
    if checks is None:
        return 2
    results = run_checks(checks, base, os.environ.get("PREVIEW_TOKEN"), os.environ.get("API_CHECK_LOG"))
    print(render(results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
