#!/usr/bin/env python3
# Seeded-bug screen for the tester (.wayfinder orchestrator-hardening, ticket 07).
#
# The reviewer has had seeded-bug fixtures since #33; nothing showed whether the tester fails a broken app, and the tester
# has twice marked a check passed that it could not have observed. This runs the real tester prompt (agents/prompts/tester.md)
# against a small flagged feature served locally, once correct and several times with exactly one bug seeded, and measures
# how often the tester notices.
#
# The app under test is the Starter Template with a notes API behind the flag `notes-api`. A local stub stands in for
# GrowthBook (kill switch on), so nothing touches production. The tester gets the spec, a git checkout with a "previous
# release" commit and a head commit (so `git log -p flags.json` shows the new flag), the app's URL and a Preview Token.
#
# Scoring, per run: the tester's report is read the way the Orchestrator reads it (`derive_test`, which also downgrades a
# `passed` check whose evidence admits it was not observed). A buggy app is caught if that says "not passed"; it is caught
# for the right reason if a failing check also matches the fixture's pattern. The correct app must pass.
#
#   python3 agents/smoke-tester/run.py --validate    no model: prove the correct feature passes an independent checker and every
#                                                    seeded bug is observable from outside (needs npm)
#   python3 agents/smoke-tester/run.py               run the screen (needs openhands and DEEPINFRA_API_KEY; costs real money,
#                                                    about $0.05 to $0.12 per run)
#
# Env: FIXTURES (comma-separated ids, default all), TRIALS (per fixture, default 2), WORKERS (default 3), TIMEOUT_MIN (per run,
# default 20), MODEL (default the tester in agents/profiles.yml), KEEP=1 (keep the working directories).
# Writes smoke-tester-results.json.
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
from build_run import verify_deployed_app  # noqa: E402
from shared import agent_output, config, prompts  # noqa: E402

_spec = importlib.util.spec_from_file_location("smoke_coder", ROOT / "agents" / "smoke-coder" / "run.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)  # its helpers: base copy with deps installed, env, mount, cost

SLUG = "evalapp"
TOKEN = "eval-preview-token"
MOUNT = {"import": 'import { notesRouter } from "./routes/notes";', "use": "app.use(notesRouter());"}


# --- pure logic (unit-tested) -------------------------------------------------


def apply_edits(source, edits):
    # The base source with each [old, new] edit applied exactly once; an edit that does not apply is an error, so a
    # fixture cannot silently turn into the correct feature.
    for old, new in edits:
        if source.count(old) != 1:
            raise ValueError(f"edit does not apply exactly once ({source.count(old)} matches): {old[:60]!r}")
        source = source.replace(old, new, 1)
    return source


def spec_for(fixtures, fixture):
    return fixtures["spec"] + (fixtures["spec_unobservable"] if fixture.get("unobservable") else "")


def judge(fixture, doc, flag):
    # Score one tester report against what the fixture expects. Returns
    # {"outcome": caught|missed|false_alarm|correct|unusable, "right_reason": bool|None, "failed": [...]}.
    # `doc` is the report as parsed (or None). The Orchestrator's own reading is used: derive_test.
    if doc is None:
        return {"outcome": "unusable", "right_reason": None, "failed": []}
    try:
        passed, failures = verify_deployed_app.derive_test(doc, [flag])
    except ValueError:
        return {"outcome": "unusable", "right_reason": None, "failed": []}
    failed = [f"{r.get('check', '')} | {r.get('evidence', '')}" for r in failures if isinstance(r, dict)]
    observed_failure = any(verify_deployed_app.check_state(r) == "failed" for r in doc.get("results", []) if isinstance(r, dict))
    if not passed and not observed_failure and fixture["expect"] != "not_pass":
        # Nothing was run (every check not_run or blocked: seen when the tester could not execute curl). The Orchestrator rightly
        # refuses to release that, but it says nothing about whether the tester can find this bug, so it is not counted either way.
        return {"outcome": "inconclusive", "right_reason": None, "failed": failed}
    if fixture["expect"] == "pass":
        return {"outcome": "correct" if passed else "false_alarm", "right_reason": None, "failed": failed}
    if passed:
        return {"outcome": "missed", "right_reason": None, "failed": failed}
    right = bool(re.search(fixture.get("match", ""), " ".join(failed), re.I)) if fixture.get("match") else None
    return {"outcome": "caught", "right_reason": right, "failed": failed}


def summarize(results, fixtures):
    # Per fixture and overall: how often a bug was caught, caught for the right reason, and a correct app flagged.
    rows, by = [], {f["id"]: f for f in fixtures}
    for fid, fixture in by.items():
        mine = [r for r in results if r["fixture"] == fid]
        if not mine:
            continue
        n = len(mine)
        rows.append({"fixture": fid, "expect": fixture["expect"], "hard": bool(fixture.get("hard")), "runs": n,
                     "caught": sum(r["outcome"] == "caught" for r in mine), "right_reason": sum(r.get("right_reason") is True for r in mine),
                     "missed": sum(r["outcome"] == "missed" for r in mine), "false_alarm": sum(r["outcome"] == "false_alarm" for r in mine),
                     "correct": sum(r["outcome"] == "correct" for r in mine), "unusable": sum(r["outcome"] == "unusable" for r in mine),
                     "inconclusive": sum(r["outcome"] == "inconclusive" for r in mine),
                     "cost": round(sum(r.get("cost", 0) for r in mine), 4)})
    buggy = [r for r in rows if r["expect"] != "pass"]
    good = [r for r in rows if r["expect"] == "pass"]
    total = sum(r["runs"] - r["inconclusive"] - r["unusable"] for r in buggy)  # only runs that actually tested something
    return {"rows": rows, "inconclusive_runs": sum(r["inconclusive"] + r["unusable"] for r in rows),
            "detection_rate": round(sum(r["caught"] for r in buggy) / total, 2) if total else None,
            "right_reason_rate": round(sum(r["right_reason"] for r in buggy) / total, 2) if total else None,
            "false_alarm_rate": round(sum(r["false_alarm"] for r in good) / max(1, sum(r["runs"] for r in good)), 2) if good else None,
            "cost": round(sum(r["cost"] for r in rows), 4)}


# --- the app under test ---------------------------------------------------------


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class GrowthBookStub:
    # Serves the SDK payload GrowthBook would: the kill switch on, no other flags (a feature flag that is not in the payload
    # reads as off, which is how a dark feature behaves).

    def __init__(self):
        slug = SLUG

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"status": 200, "features": {f"{slug}.global-kill-switch": {"defaultValue": True}},
                                   "dateUpdated": "2026-01-01T00:00:00Z"}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", free_port()), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


def build_checkout(base, fixtures, fixture, dest):
    # A git checkout with a 'previous release' commit (the Starter Template) and a head commit (the feature and its flag).
    shutil.copytree(base, dest, symlinks=True)
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "smoke@ai-factory.local"],
                ["git", "config", "user.name", "smoke"], ["git", "add", "-A"], ["git", "commit", "-qm", "previous release"]):
        sc.run(cmd, dest)
    source = apply_edits((HERE / "base" / "notes.ts").read_text(), fixture["edits"])
    (dest / "backend" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (dest / "backend" / "src" / "routes" / "notes.ts").write_text(source)
    sc.mount(dest, MOUNT)
    flags = json.loads((dest / "flags.json").read_text() or "[]")
    flags.append({"slug": fixtures["flag"], "description": "Notes API"})
    (dest / "flags.json").write_text(json.dumps(flags, indent=2) + "\n")
    for cmd in (["git", "add", "-A"], ["git", "commit", "-qm", f"Add notes API behind {fixtures['flag']}"]):
        sc.run(cmd, dest)
    return sc.run(["git", "rev-parse", "HEAD"], dest)[1].strip()


class RunningApp:
    def __init__(self, workdir):
        self.stub = GrowthBookStub()
        self.port = free_port()
        env = {**sc.minimal_env(), "PORT": str(self.port), "APP_SLUG": SLUG, "GROWTHBOOK_CLIENT_KEY": "sdk-eval",
               "GROWTHBOOK_API_HOST": self.stub.url, "PREVIEW_TOKEN": TOKEN}
        self.log = open(workdir / "app.log", "w")
        self.proc = subprocess.Popen([str(workdir / "node_modules" / ".bin" / "tsx"), "src/index.ts"], cwd=workdir / "backend", env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        self.url = f"http://127.0.0.1:{self.port}"
        end = time.time() + 90
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("the app exited while starting; see app.log")
            if http("GET", self.url + "/api/health")[0] == 200:
                return
            time.sleep(0.5)
        raise RuntimeError("the app did not become healthy in 90 s")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.stub.stop()
        self.log.close()


def http(method, url, body=None, token=False, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("content-type", "application/json")
    if token:
        req.add_header("x-preview-token", TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, raw
    except (urllib.error.URLError, OSError):
        return 0, None


def oracle(base):
    # An independent checker for the spec: [(check name, ok)]. It is the answer key, not part of the tester.
    out = []
    url = base + "/api/notes"
    out.append(("dark without the token", http("GET", url)[0] == 404 and http("POST", url, {"text": "x"})[0] == 404))
    status, a = http("POST", url, {"text": "  first  "}, True)
    out.append(("create answers 201", status == 201))
    out.append(("create trims and returns id and text", isinstance(a, dict) and a.get("text") == "first" and isinstance(a.get("id"), int)))
    status, b2 = http("POST", url, {"text": "second"}, True)
    out.append(("ids are unique", isinstance(a, dict) and isinstance(b2, dict) and a.get("id") != b2.get("id")))
    out.append(("blank text answers 400", http("POST", url, {"text": "   "}, True)[0] == 400))
    out.append(("missing text answers 400", http("POST", url, {}, True)[0] == 400))
    out.append(("non-string text answers 400", http("POST", url, {"text": 5}, True)[0] == 400))
    status, listing = http("GET", url, token=True)
    out.append(("list is in creation order", status == 200 and isinstance(listing, list) and [n.get("text") for n in listing[:2]] == ["first", "second"]))
    one = a.get("id") if isinstance(a, dict) else 1
    out.append(("get by id answers 200", http("GET", f"{url}/{one}", token=True)[0] == 200))
    out.append(("unknown id answers 404", http("GET", f"{url}/99999", token=True)[0] == 404))
    out.append(("id 0 answers 400", http("GET", f"{url}/0", token=True)[0] == 400))
    out.append(("id abc answers 400", http("GET", f"{url}/abc", token=True)[0] == 400))
    out.append(("id 1abc answers 400", http("GET", f"{url}/1abc", token=True)[0] == 400))
    return out


# --- the screen -------------------------------------------------------------------


def load():
    return json.loads((HERE / "fixtures.json").read_text())


def validate():
    # No model: the correct feature passes the independent checker, and every seeded bug fails at least the check it should.
    data, ok = load(), True
    with tempfile.TemporaryDirectory() as tmp:
        base = sc.prepare_base(Path(tmp))
        for fixture in data["fixtures"]:
            dest = Path(tmp) / fixture["id"]
            build_checkout(base, data, fixture, dest)
            app = RunningApp(dest)
            try:
                results = oracle(app.url)
            finally:
                app.stop()
            failing = [name for name, good in results if not good]
            if fixture["expect"] == "pass":
                good = not failing
            else:
                want = fixture.get("oracle_fails", [])
                good = (set(want) <= set(failing)) if want else not failing  # an unobservable bug fails no check
            ok &= good
            print(f"{'OK  ' if good else 'FAIL'} {fixture['id']}: oracle fails {failing or 'nothing'}"
                  + ("" if good else f"  (wanted {fixture.get('oracle_fails', 'nothing')})"))
    sys.exit(0 if ok else 1)


def one_run(job):
    fixture, trial, data, base, root, key, base_url, model, timeout_min, prices = job
    name = f"{fixture['id']}-{trial}"
    result = {"fixture": fixture["id"], "trial": trial}
    app = None
    try:
        dest, home = root / name, root / f"home-{name}"
        head = build_checkout(base, data, fixture, dest)
        app = RunningApp(dest)
        report, api_log = root / f"report-{name}.json", root / f"api-check-{name}.jsonl"
        prompt = prompts.render(prompts.load_prompt(str(ROOT / "agents" / "prompts" / "tester.md")), {
            "app_name": "smoke-app", "build_kind": "update", "spec": spec_for(data, fixture), "app_url": app.url, "head_sha": head,
            "report_path": report, "previous_report": "none (this is the first test pass)", "api_check": verify_deployed_app.API_CHECK, "ui_section": ""})
        home.mkdir(parents=True, exist_ok=True)
        env = {**sc.minimal_env(home), "LLM_MODEL": "openai/" + model, "LLM_BASE_URL": base_url, "LLM_API_KEY": key, "RUNTIME": "process",
               "PREVIEW_TOKEN": TOKEN, "API_CHECK_BASE": app.url, "API_CHECK_LOG": str(api_log)}
        began = time.time()
        try:
            with open(root / f"agent-{name}.log", "w") as log:  # kept: without it a run that quits at once cannot be diagnosed
                rc = subprocess.run(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd=dest, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=timeout_min * 60).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
        result.update(secs=round(time.time() - began, 1), exit=rc)
        cost = 0.0
        for state_file in sorted((home / ".openhands" / "conversations").glob("*/base_state.json")):
            cost = sc.cost_of(json.loads(state_file.read_text()), prices.get(model, {}))
        result["cost"] = round(cost, 4)
        doc = agent_output.load_json(report)
        if doc is not None:  # the Orchestrator reads the report this way: the helper's observations outrank the tester's judgement
            doc = verify_deployed_app.reconcile_api_checks(doc, verify_deployed_app.load_api_results(api_log))
        result["helper_checks"] = len(verify_deployed_app.load_api_results(api_log))
        result.update(judge(fixture, doc, data["flag"]))
        result["json_problem"] = agent_output.json_problem(report) if doc is None else None
        if doc is None:  # say why, from the agent's own output
            tail = (root / f"agent-{name}.log").read_text(errors="replace")[-600:] if (root / f"agent-{name}.log").exists() else ""
            result["agent_output_tail"] = re.sub(r"\s+", " ", tail).strip()
    except Exception as e:  # noqa: BLE001 - a broken run is a result, not a crash of the screen
        result.update(outcome="unusable", right_reason=None, failed=[], error=f"{type(e).__name__}: {e}")
    finally:
        if app:
            app.stop()
    return result


def main():
    if "--validate" in sys.argv:
        validate()
    key = os.environ["DEEPINFRA_API_KEY"]
    cfg = config.load()
    model = os.environ.get("MODEL") or cfg["roles"]["tester"]["model"]
    base_url = cfg["provider"]["base_url"]
    data = load()
    only = set(filter(None, os.environ.get("FIXTURES", "").split(",")))
    fixtures = [f for f in data["fixtures"] if not only or f["id"] in only]
    trials, workers, timeout_min = int(os.environ.get("TRIALS", "2")), int(os.environ.get("WORKERS", "3")), int(os.environ.get("TIMEOUT_MIN", "20"))
    root = Path(tempfile.mkdtemp(prefix="smoke-tester-"))
    base = sc.prepare_base(root)
    prices = sc.fetch_prices()
    jobs = [(f, i, data, base, root, key, base_url, model, timeout_min, prices) for f in fixtures for i in range(1, trials + 1)]
    print(f"{len(jobs)} runs of {model}: {len(fixtures)} fixture(s) x {trials} trial(s), {workers} at a time", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(one_run, jobs):
            results.append(r)
            print(f"{r['outcome']:<11} {r['fixture']}#{r['trial']}  {r.get('secs', '-')}s  ${r.get('cost', 0)}  "
                  f"{'' if r.get('right_reason') in (True, None) else '(wrong reason) '}{(r.get('failed') or [''])[0][:110]}", flush=True)
    summary = summarize(results, fixtures)
    print("\nfixture | expect | runs | caught | right reason | missed | false alarm | inconclusive/unusable")
    for r in summary["rows"]:
        print(f"{r['fixture']}{' (hard)' if r['hard'] else ''} | {r['expect']} | {r['runs']} | {r['caught']} | {r['right_reason']} | "
              f"{r['missed']} | {r['false_alarm']} | {r['inconclusive']}/{r['unusable']}")
    print(f"\ndetection {summary['detection_rate']}  right reason {summary['right_reason_rate']}  false alarms {summary['false_alarm_rate']}  "
          f"inconclusive runs {summary['inconclusive_runs']}  cost ${summary['cost']}")
    Path("smoke-tester-results.json").write_text(json.dumps({"model": model, "summary": summary, "runs": results}, indent=2))
    if not os.environ.get("KEEP"):
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
