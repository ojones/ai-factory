#!/usr/bin/env python3
"""ui-check: the tester states what a page should show and do; this drives a real browser, observes, and compares.

The browser counterpart of api_check.py, for the part of a Managed App only a browser sees: what renders, what a form does, what a
flagged control looks like with and without the Preview Token. The model's job is to say *which* screens and interactions the spec
calls for and what each should show. This opens the page headless (Chromium through Playwright), performs the steps, reads what is
actually there and compares it mechanically. Every result is appended to `$UI_CHECK_LOG`, which the Orchestrator reads
(build_run.reconcile_ui_checks), so a failure the helper saw cannot be reported as a pass or left out.

  python3 ui_check.py checks.json [--base https://app.fly.dev]

Env: PREVIEW_TOKEN (opens the page with the Preview Token for a check with "auth": "preview"; never printed, logged or screenshotted),
UI_CHECK_BASE (the base URL if --base is not given), UI_CHECK_LOG (JSONL results), UI_CHECK_DIR (where failure screenshots go),
PLAYWRIGHT_BROWSERS_PATH. Exit 0 if every check passed, 1 if any failed, 2 if the file is unusable.

A checks file is {"checks": [...]}. Each check is a scenario in a fresh browser context:

  {"id": "add-todo", "name": "Adding a todo shows it in the list", "start": "/", "auth": "preview" | "none",
   "steps": [{"fill": {"label": "New todo", "value": "factory-test-a"}}, {"click": {"role": "button", "name": "Add"}},
             {"press": "Enter"}, {"goto": "/other"}, {"wait_for": {"text": "factory-test-a"}}, {"check": {"label": "Done"}}],
   "expect": {"visible": [LOC], "hidden": [LOC], "text": [{...LOC, "contains": "x"} or {...LOC, "equals": "x"}],
              "count": [{...LOC, "is": 1}], "url_path": "/", "title_contains": "Todo", "no_console_errors": true}}

LOC (a locator) is one of {"role": "button", "name": "Add"}, {"label": "New todo"}, {"text": "Hello"}, {"placeholder": "..."},
{"test_id": "..."}, with optional "exact": true. Role and label locators are preferred: they are what a user sees. Checks run in order,
at most 30 per file and 20 steps per check, 8 seconds per action, and only the base URL's origin is ever requested.
"""
import json
import os
import re
import sys
import time

MAX_CHECKS, MAX_STEPS = 30, 20
ACTION_TIMEOUT_MS, NAV_TIMEOUT_MS = 8000, 15000
TEXT_LIMIT = 300
ACTIONS = ("click", "fill", "press", "goto", "wait_for", "check", "select")
LOCATORS = ("role", "label", "text", "placeholder", "test_id")


# --- pure logic (unit-tested) -------------------------------------------------


def loc_key(loc):
    """A short readable name for a locator, used in problems and as the key of what was observed."""
    kind = next((k for k in LOCATORS if k in loc), None)
    if kind is None:
        return "?"
    name = f" name={loc['name']!r}" if kind == "role" and loc.get("name") else ""
    return f"{kind}={loc[kind]!r}{name}"


def valid_locator(loc):
    return isinstance(loc, dict) and sum(k in loc for k in LOCATORS) == 1 and isinstance(loc[next(k for k in LOCATORS if k in loc)], str)


def validate(doc):
    """(checks, error). Unique ids, known actions, valid locators, and only paths on the base URL."""
    checks = doc.get("checks") if isinstance(doc, dict) else doc
    if not isinstance(checks, list) or not checks:
        return None, "the file needs a non-empty list of checks"
    if len(checks) > MAX_CHECKS:
        return None, f"at most {MAX_CHECKS} checks per file"
    seen = set()
    for i, c in enumerate(checks):
        if not isinstance(c, dict) or not isinstance(c.get("expect"), dict) or not c["expect"]:
            return None, f"check {i + 1} needs a non-empty `expect`"
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip() or cid in seen:
            return None, f"check {i + 1} needs a unique string `id`"
        seen.add(cid)
        for path in [c.get("start", "/")] + [s["goto"] for s in c.get("steps", []) if isinstance(s, dict) and "goto" in s]:
            if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "://" in path:
                return None, f"check {cid}: paths must start with a single / (only the base URL is ever opened)"
        steps = c.get("steps", [])
        if not isinstance(steps, list) or len(steps) > MAX_STEPS:
            return None, f"check {cid}: `steps` must be a list of at most {MAX_STEPS}"
        for s in steps:
            action = next((a for a in ACTIONS if isinstance(s, dict) and a in s), None)
            if action is None:
                return None, f"check {cid}: a step must be one of {', '.join(ACTIONS)}"
            arg = s[action]
            if action in ("click", "wait_for", "check", "fill", "select") and not valid_locator(arg):
                return None, f"check {cid}: `{action}` needs a locator (exactly one of {', '.join(LOCATORS)})"
            if action in ("fill", "select") and not isinstance(arg.get("value"), str):
                return None, f"check {cid}: `{action}` needs a string `value`"
        ex = c["expect"]
        for key in ("visible", "hidden"):
            if not all(valid_locator(l) for l in ex.get(key, [])):
                return None, f"check {cid}: every `{key}` entry needs a locator"
        for key in ("text", "count"):
            if not all(valid_locator(l) for l in ex.get(key, [])):
                return None, f"check {cid}: every `{key}` entry needs a locator"
    return checks, None


def compare(expect, obs):
    """The problems found when what the page showed (`obs`) is held against `expect`. Empty: the check passed.
    obs: {"visible": {key: bool}, "text": {key: str or None}, "count": {key: int}, "url_path": str, "title": str, "console_errors": [str]}"""
    problems = []
    for loc in expect.get("visible", []):
        if not obs["visible"].get(loc_key(loc)):
            problems.append(f"{loc_key(loc)}: expected it to be visible, but it is not")
    for loc in expect.get("hidden", []):
        if obs["visible"].get(loc_key(loc)):
            problems.append(f"{loc_key(loc)}: expected it to be hidden or absent, but it is visible")
    for item in expect.get("text", []):
        got = obs["text"].get(loc_key(item))
        if got is None:
            problems.append(f"{loc_key(item)}: expected text, but nothing is there")
        elif "equals" in item and got.strip() != item["equals"].strip():
            problems.append(f"{loc_key(item)}: expected text {item['equals']!r}, got {got.strip()[:80]!r}")
        elif "contains" in item and item["contains"] not in got:
            problems.append(f"{loc_key(item)}: expected text containing {item['contains']!r}, got {got.strip()[:80]!r}")
    for item in expect.get("count", []):
        got = obs["count"].get(loc_key(item))
        if got != item.get("is"):
            problems.append(f"{loc_key(item)}: expected {item.get('is')} match(es), found {got}")
    if "url_path" in expect and obs["url_path"] != expect["url_path"]:
        problems.append(f"url path: expected {expect['url_path']!r}, got {obs['url_path']!r}")
    if "title_contains" in expect and expect["title_contains"] not in obs["title"]:
        problems.append(f"title: expected it to contain {expect['title_contains']!r}, got {obs['title'][:80]!r}")
    if expect.get("no_console_errors") and obs["console_errors"]:
        problems.append("console errors: " + "; ".join(e[:120] for e in obs["console_errors"][:3]))
    return problems


def scrub(text, token):
    text = (text or "")[:TEXT_LIMIT * 4]
    if token:
        text = text.replace(token, "[TOKEN]")
    return re.sub(r"([?&]preview=)[^&\s\"']+", r"\1[TOKEN]", text)


def render(results):
    lines = []
    for r in results:
        if r["ok"]:
            lines.append(f"PASS {r['id']}: {r['name']}")
        else:
            lines.append(f"FAIL {r['id']}: {r['name']}\n     " + "; ".join(r["problems"]) + (f"\n     screenshot: {r['screenshot']}" if r.get("screenshot") else ""))
    failed = sum(not r["ok"] for r in results)
    lines.append(f"{len(results) - failed} passed, {failed} failed")
    return "\n".join(lines)


# --- running (needs Playwright) -------------------------------------------------


def locate(page, loc):
    exact = bool(loc.get("exact"))
    if "role" in loc:
        return page.get_by_role(loc["role"], name=loc.get("name"), exact=exact) if loc.get("name") else page.get_by_role(loc["role"])
    if "label" in loc:
        return page.get_by_label(loc["label"], exact=exact)
    if "text" in loc:
        return page.get_by_text(loc["text"], exact=exact)
    if "placeholder" in loc:
        return page.get_by_placeholder(loc["placeholder"], exact=exact)
    return page.get_by_test_id(loc["test_id"])


EXPECT_PATIENCE_S = 4.0


def observe(page, expect, console_errors, token, text_timeout=3000):
    obs = {"visible": {}, "text": {}, "count": {}, "url_path": "", "title": "", "console_errors": [scrub(e, token) for e in console_errors]}
    for loc in expect.get("visible", []) + expect.get("hidden", []):
        try:
            obs["visible"][loc_key(loc)] = locate(page, loc).first.is_visible(timeout=1000)
        except Exception:  # noqa: BLE001 - absent counts as not visible
            obs["visible"][loc_key(loc)] = False
    for item in expect.get("text", []):
        try:
            obs["text"][loc_key(item)] = scrub(locate(page, item).first.inner_text(timeout=text_timeout), token)
        except Exception:  # noqa: BLE001
            obs["text"][loc_key(item)] = None
    for item in expect.get("count", []):
        try:
            obs["count"][loc_key(item)] = locate(page, item).count()
        except Exception:  # noqa: BLE001
            obs["count"][loc_key(item)] = -1
    from urllib.parse import urlparse
    obs["url_path"] = urlparse(page.url).path or "/"
    obs["title"] = scrub(page.title(), token)
    return obs


def settle(page, expect, console_errors, token, patience=EXPECT_PATIENCE_S):
    """What the page shows once it has had a few seconds to settle, with the problems found. A page updates after a network call, so
    the expectations are re-read until they hold or the patience runs out (the way Playwright's own assertions wait), and only the
    last reading counts. Without this a correct page fails because the check looked a moment too soon."""
    deadline = time.time() + patience
    while True:
        obs = observe(page, expect, console_errors, token, text_timeout=400)
        problems = compare(expect, obs)
        if not problems or time.time() >= deadline:
            return obs, problems
        page.wait_for_timeout(250)


def do_step(page, step, base):
    action = next(a for a in ACTIONS if a in step)
    arg = step[action]
    if action == "click":
        locate(page, arg).first.click(timeout=ACTION_TIMEOUT_MS)
    elif action == "fill":
        locate(page, arg).first.fill(arg["value"], timeout=ACTION_TIMEOUT_MS)
    elif action == "select":
        locate(page, arg).first.select_option(arg["value"], timeout=ACTION_TIMEOUT_MS)
    elif action == "check":
        locate(page, arg).first.check(timeout=ACTION_TIMEOUT_MS)
    elif action == "press":
        page.keyboard.press(str(arg))
    elif action == "goto":
        page.goto(base.rstrip("/") + arg, timeout=NAV_TIMEOUT_MS)
    elif action == "wait_for":
        locate(page, arg).first.wait_for(timeout=ACTION_TIMEOUT_MS)


def run_checks(checks, base, token, log_path=None, shot_dir=None):
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse
    origin = "{0.scheme}://{0.netloc}".format(urlparse(base))
    results = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001 - some runners forbid the sandbox to an unprivileged account; the browser only opens the app's own origin
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        for c in checks:
            began, problems, obs, shot = time.time(), [], None, None
            ctx = browser.new_context(viewport={"width": 1100, "height": 800})
            ctx.set_default_timeout(ACTION_TIMEOUT_MS)
            ctx.route("**/*", lambda route, request: route.continue_() if request.url.startswith(origin) or request.url.startswith("data:") else route.abort())
            page, console_errors = ctx.new_page(), []
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            try:
                if c.get("auth") == "preview":
                    if not token:
                        raise RuntimeError("PREVIEW_TOKEN is not set in the environment, so an auth: preview check cannot be made")
                    page.goto(f"{base.rstrip('/')}/?preview={token}", timeout=NAV_TIMEOUT_MS)  # sets the HttpOnly preview cookie
                page.goto(base.rstrip("/") + c.get("start", "/"), timeout=NAV_TIMEOUT_MS)
                for step in c.get("steps", []):
                    do_step(page, step, base)
                obs, problems = settle(page, c["expect"], console_errors, token)
            except Exception as e:  # noqa: BLE001 - a timeout or a failed navigation is a failed check, with the reason
                problems = [scrub(f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}", token)]
            if problems and shot_dir:
                try:
                    os.makedirs(shot_dir, exist_ok=True)
                    shot = f"ui-{re.sub(r'[^A-Za-z0-9_-]', '_', c['id'])}.png"
                    page.screenshot(path=os.path.join(shot_dir, shot))
                except Exception:  # noqa: BLE001
                    shot = None
            ctx.close()
            res = {"id": c["id"], "name": c.get("name") or c["id"], "ok": not problems, "problems": problems, "expected": c["expect"],
                   "observed": obs or {}, "ms": round((time.time() - began) * 1000), "screenshot": shot}
            results.append(res)
            if log_path:
                with open(log_path, "a") as f:
                    f.write(json.dumps(res) + "\n")
        browser.close()
    return results


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    base = os.environ.get("UI_CHECK_BASE", "")
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]
        args = [a for a in args if a != base]
    if len(args) != 1 or not base.startswith(("http://", "https://")):
        print("usage: ui_check.py checks.json --base https://host   (or set UI_CHECK_BASE)", file=sys.stderr)
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
    results = run_checks(checks, base, os.environ.get("PREVIEW_TOKEN"), os.environ.get("UI_CHECK_LOG"), os.environ.get("UI_CHECK_DIR"))
    print(render(results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
