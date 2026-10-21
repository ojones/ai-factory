#!/usr/bin/env python3
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

MAX_CHECKS, MAX_STEPS = 30, 20
ACTION_TIMEOUT_MS, NAV_TIMEOUT_MS = 8000, 15000
TEXT_LIMIT = 300
ACTIONS = ("click", "fill", "press", "goto", "wait_for", "check", "select")
LOCATORS = ("role", "label", "text", "placeholder", "test_id")


def loc_key(loc):
    kind = next((k for k in LOCATORS if k in loc), None)
    if kind is None:
        return "?"
    name = f" name={loc['name']!r}" if kind == "role" and loc.get("name") else ""
    return f"{kind}={loc[kind]!r}{name}"


def valid_locator(loc):
    return isinstance(loc, dict) and sum(k in loc for k in LOCATORS) == 1 and isinstance(loc[next(k for k in LOCATORS if k in loc)], str)


def bad_path(path):
    return not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "://" in path


def step_problem(cid, step):
    action = next((a for a in ACTIONS if isinstance(step, dict) and a in step), None)
    if action is None:
        return f"check {cid}: a step must be one of {', '.join(ACTIONS)}"
    arg = step[action]
    if action in ("click", "wait_for", "check", "fill", "select") and not valid_locator(arg):
        return f"check {cid}: `{action}` needs a locator (exactly one of {', '.join(LOCATORS)})"
    if action in ("fill", "select") and not isinstance(arg.get("value"), str):
        return f"check {cid}: `{action}` needs a string `value`"
    return None


def steps_problem(cid, c):
    steps = c.get("steps", [])
    paths = [c.get("start", "/")] + [s["goto"] for s in steps if isinstance(s, dict) and "goto" in s]
    if any(bad_path(path) for path in paths):
        return f"check {cid}: paths must start with a single / (only the base URL is ever opened)"
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        return f"check {cid}: `steps` must be a list of at most {MAX_STEPS}"
    return next(filter(None, (step_problem(cid, s) for s in steps)), None)


def expect_problem(cid, expect):
    for key in ("visible", "hidden", "text", "count"):
        if not all(valid_locator(l) for l in expect.get(key, [])):
            return f"check {cid}: every `{key}` entry needs a locator"
    return None


def check_problem(i, c, seen):
    if not isinstance(c, dict) or not isinstance(c.get("expect"), dict) or not c["expect"]:
        return f"check {i + 1} needs a non-empty `expect`"
    cid = c.get("id")
    if not isinstance(cid, str) or not cid.strip() or cid in seen:
        return f"check {i + 1} needs a unique string `id`"
    seen.add(cid)
    return steps_problem(cid, c) or expect_problem(cid, c["expect"])


def validate(doc):
    checks = doc.get("checks") if isinstance(doc, dict) else doc
    if not isinstance(checks, list) or not checks:
        return None, "the file needs a non-empty list of checks"
    if len(checks) > MAX_CHECKS:
        return None, f"at most {MAX_CHECKS} checks per file"
    seen = set()
    problem = next(filter(None, (check_problem(i, c, seen) for i, c in enumerate(checks))), None)
    return (None, problem) if problem else (checks, None)


def visibility_problems(expect, obs):
    problems = [f"{loc_key(loc)}: expected it to be visible, but it is not" for loc in expect.get("visible", []) if not obs["visible"].get(loc_key(loc))]
    return problems + [f"{loc_key(loc)}: expected it to be hidden or absent, but it is visible" for loc in expect.get("hidden", []) if obs["visible"].get(loc_key(loc))]


def text_problem(item, got):
    key = loc_key(item)
    if got is None:
        return f"{key}: expected text, but nothing is there"
    if "equals" in item and got.strip() != item["equals"].strip():
        return f"{key}: expected text {item['equals']!r}, got {got.strip()[:80]!r}"
    if "contains" in item and item["contains"] not in got:
        return f"{key}: expected text containing {item['contains']!r}, got {got.strip()[:80]!r}"
    return None


def count_problems(expect, obs):
    found = [(item, obs["count"].get(loc_key(item))) for item in expect.get("count", [])]
    return [f"{loc_key(item)}: expected {item.get('is')} match(es), found {got}" for item, got in found if got != item.get("is")]


def page_problems(expect, obs):
    problems = []
    if "url_path" in expect and obs["url_path"] != expect["url_path"]:
        problems.append(f"url path: expected {expect['url_path']!r}, got {obs['url_path']!r}")
    if "title_contains" in expect and expect["title_contains"] not in obs["title"]:
        problems.append(f"title: expected it to contain {expect['title_contains']!r}, got {obs['title'][:80]!r}")
    if expect.get("no_console_errors") and obs["console_errors"]:
        problems.append("console errors: " + "; ".join(e[:120] for e in obs["console_errors"][:3]))
    return problems


def compare(expect, obs):
    texts = filter(None, (text_problem(item, obs["text"].get(loc_key(item))) for item in expect.get("text", [])))
    return visibility_problems(expect, obs) + list(texts) + count_problems(expect, obs) + page_problems(expect, obs)


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
    obs["url_path"] = urlparse(page.url).path or "/"
    obs["title"] = scrub(page.title(), token)
    return obs


def settle(page, expect, console_errors, token, patience=EXPECT_PATIENCE_S):
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
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    origin = "{0.scheme}://{0.netloc}".format(urlparse(base))
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        for c in checks:
            results.append(run_one_check(browser, origin, c, base, token, shot_dir))
            append_result(log_path, results[-1])
        browser.close()
    return results


def launch_browser(p):
    try:
        return p.chromium.launch(headless=True)
    except Exception:  # noqa: BLE001 - some runners forbid the sandbox to an unprivileged account; the browser only opens the app's own origin
        return p.chromium.launch(headless=True, args=["--no-sandbox"])


def append_result(log_path, res):
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(res) + "\n")


def run_one_check(browser, origin, c, base, token, shot_dir):
    began = time.time()
    ctx, page, console_errors = open_page(browser, origin)
    obs, problems = attempt_check(page, c, base, token, console_errors)
    shot = take_screenshot(page, c, shot_dir) if problems and shot_dir else None
    ctx.close()
    return {"id": c["id"], "name": c.get("name") or c["id"], "ok": not problems, "problems": problems, "expected": c["expect"],
            "observed": obs or {}, "ms": round((time.time() - began) * 1000), "screenshot": shot}


def open_page(browser, origin):
    ctx = browser.new_context(viewport={"width": 1100, "height": 800})
    ctx.set_default_timeout(ACTION_TIMEOUT_MS)
    ctx.route("**/*", lambda route, request: route.continue_() if request.url.startswith(origin) or request.url.startswith("data:") else route.abort())
    page, console_errors = ctx.new_page(), []
    page.on("console", lambda m, errs=console_errors: errs.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e, errs=console_errors: errs.append(str(e)))
    return ctx, page, console_errors


def attempt_check(page, c, base, token, console_errors):
    try:
        open_start_page(page, c, base, token)
        for step in c.get("steps", []):
            do_step(page, step, base)
        return settle(page, c["expect"], console_errors, token)
    except Exception as e:  # noqa: BLE001 - a timeout or a failed navigation is a failed check, with the reason
        return None, [scrub(f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}", token)]


def open_start_page(page, c, base, token):
    if c.get("auth") == "preview":
        if not token:
            raise RuntimeError("PREVIEW_TOKEN is not set in the environment, so an auth: preview check cannot be made")
        page.goto(f"{base.rstrip('/')}/?preview={token}", timeout=NAV_TIMEOUT_MS)
    page.goto(base.rstrip("/") + c.get("start", "/"), timeout=NAV_TIMEOUT_MS)


def take_screenshot(page, c, shot_dir):
    try:
        Path(shot_dir).mkdir(parents=True, exist_ok=True)
        shot = f"ui-{re.sub(r'[^A-Za-z0-9_-]', '_', c['id'])}.png"
        page.screenshot(path=str(Path(shot_dir) / shot))
        return shot
    except Exception:  # noqa: BLE001
        return None


def read_args(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    base = os.environ.get("UI_CHECK_BASE", "")
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
        print("usage: ui_check.py checks.json --base https://host   (or set UI_CHECK_BASE)", file=sys.stderr)
        return 2
    checks = load_checks(args[0])
    if checks is None:
        return 2
    results = run_checks(checks, base, os.environ.get("PREVIEW_TOKEN"), os.environ.get("UI_CHECK_LOG"), os.environ.get("UI_CHECK_DIR"))
    print(render(results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
