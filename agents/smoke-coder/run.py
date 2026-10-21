#!/usr/bin/env python3
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
from shared import agent_usage, config, prompts, starter_template  # noqa: E402

TEMPLATE = ROOT / "templates" / "starter"
TASKS_DIR = HERE / "tasks"
MIN_ENV_KEYS = ("PATH", "HOME", "LANG", "TMPDIR", "CI")


def minimal_env(home=None):
    env = {k: os.environ[k] for k in MIN_ENV_KEYS if k in os.environ}
    if home:
        env["HOME"] = str(home)
    return env


def run(cmd, cwd, env=None, timeout=600):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env or minimal_env(), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-30000:]
    except subprocess.TimeoutExpired:
        return "timeout", ""


def digest(out):
    keep = [l.strip() for l in out.splitlines()
            if re.search(r"FAIL|AssertionError|expected|error TS|Error:|✗|×|Cannot find", l) and "npm error" not in l]
    return " | ".join(keep[:8])[:700] or out[-300:]


def load_tasks(only=None):
    tasks = []
    for d in sorted(TASKS_DIR.iterdir()):
        if d.is_dir() and (not only or d.name in only):
            tasks.append({"id": d.name, "dir": d, **json.loads((d / "task.json").read_text())})
    return tasks


def overlay(src, dst):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def mount(workdir, spec):
    app = workdir / "backend" / "src" / "app.ts"
    text = app.read_text()
    text = text.replace('import { healthRouter } from "./routes/health";',
                        'import { healthRouter } from "./routes/health";\n' + spec["import"], 1)
    marker = "  // One container: the backend serves"
    text = text.replace(marker, f"  {spec['use']}\n\n" + marker, 1)
    app.write_text(text)


def prepare_base(cache):
    base = cache / "base"
    shutil.copytree(TEMPLATE, base, ignore=shutil.ignore_patterns("node_modules", "dist"), symlinks=True)
    code, out = run(["npm", "ci", "--no-audit", "--no-fund"], base, timeout=900)
    if code != 0:
        sys.exit(f"npm ci failed in the base copy: {out}")
    return base


def fresh_workdir(base, task, dest):
    shutil.copytree(base, dest, symlinks=True)
    overlay(task["dir"] / "seed", dest)
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "smoke@ai-factory.local"],
                ["git", "config", "user.name", "smoke"], ["git", "add", "-A"], ["git", "commit", "-qm", "seed"]):
        run(cmd, dest)


def score(workdir, task, base_sha):
    count = run(["git", "rev-list", "--count", f"{base_sha}..HEAD"], workdir)[1].strip()
    if not count.isdigit() or int(count) == 0:
        return False, "no commit"
    changed = run(["git", "diff", "--name-only", f"{base_sha}..HEAD"], workdir)[1].split("\n")
    bad = starter_template.protected_violations([c for c in changed if c])
    if bad:
        return False, f"changed protected files: {', '.join(bad)}"
    overlay(task["dir"] / "accept", workdir / "backend" / "src" / "__tests__" / "accept")
    code, out = run(["npm", "run", "check"], workdir)
    if code != 0:
        return False, f"type-check failed: {digest(out)}"
    code, out = run(["npm", "test"], workdir)
    if code != 0:
        return False, f"tests failed: {digest(out)}"
    return True, "ok"


def fetch_prices():
    try:
        with urllib.request.urlopen("https://api.deepinfra.com/v1/openai/models", timeout=30) as r:
            return {m["id"]: m.get("metadata", {}).get("pricing") or {} for m in json.load(r).get("data", [])}
    except Exception:  # noqa: BLE001 - cost is a nicety; a run still scores without it
        return {}


def cost_of(state, price):
    total = 0.0
    for m in ((state.get("stats") or {}).get("usage_to_metrics") or {}).values():
        u = (m or {}).get("accumulated_token_usage") or {}
        prompt, cached = u.get("prompt_tokens", 0), u.get("cache_read_tokens", 0)
        total += ((prompt - cached) * price.get("input_tokens", 0) + cached * price.get("cache_read_tokens", price.get("input_tokens", 0))
                  + u.get("completion_tokens", 0) * price.get("output_tokens", 0)) / 1e6
    return total


def coder_prompt(task, findings):
    values = {"app_name": "smoke-app", "round": "1", "task": task["task"], "findings_path": findings, "build_kind": task["build_kind"]}
    return prompts.render(prompts.load_prompt(str(ROOT / "agents" / "prompts" / "coder.md")), values)


def run_coder(prompt, workdir, home, model, base_url, key, timeout_min):
    env = {**minimal_env(home), "LLM_MODEL": "openai/" + model, "LLM_BASE_URL": base_url, "LLM_API_KEY": key, "RUNTIME": "process"}
    try:
        return subprocess.run(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd=workdir, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_min * 60).returncode
    except subprocess.TimeoutExpired:
        return "timeout"


def read_usage(home, prices):
    usage, cost = None, 0.0
    for state_file in sorted((home / ".openhands" / "conversations").glob("*/base_state.json")):
        state = json.loads(state_file.read_text())
        usage, cost = agent_usage.summarize_token_usage(state), cost_of(state, prices)
    return usage or {}, cost


def trial(job, result):
    model, task, number, base, root, key, base_url, timeout_min, prices = job
    name = f"{re.sub(r'[^A-Za-z0-9]+', '-', model).strip('-')}-{task['id']}-{number}"
    workdir, home = root / name, root / f"home-{name}"
    fresh_workdir(base, task, workdir)
    base_sha = run(["git", "rev-parse", "HEAD"], workdir)[1].strip()
    findings = root / f"findings-{name}.json"
    findings.write_text('{"blocking": [], "minor": []}')
    home.mkdir(parents=True, exist_ok=True)
    began = time.time()
    rc = run_coder(coder_prompt(task, findings), workdir, home, model, base_url, key, timeout_min)
    result["secs"], result["exit"] = round(time.time() - began, 1), rc
    usage, cost = read_usage(home, prices.get(model, {}))
    result.update(calls=usage.get("calls", 0), llm_secs=usage.get("llm_seconds", 0), peak_context=usage.get("peak_context", 0), cost=round(cost, 4))
    result["passed"], result["reason"] = (False, f"coder exited {rc}") if rc == "timeout" else score(workdir, task, base_sha)


def one_run(job):
    result = {"model": job[0], "task": job[1]["id"], "trial": job[2]}
    try:
        trial(job, result)
    except Exception as e:  # noqa: BLE001 - a broken run is a result, not a crash of the screen
        result.update(passed=False, reason=f"harness error: {type(e).__name__}: {e}")
    return result


def summarize(results, models):
    rows = []
    for model in models:
        mine = [r for r in results if r["model"] == model]
        timed = [r["secs"] for r in mine if "secs" in r]
        rows.append({"model": model, "runs": len(mine), "passed": sum(1 for r in mine if r["passed"]),
                     "median_secs": statistics.median(timed) if timed else None,
                     "avg_cost": round(sum(r.get("cost", 0) for r in mine) / len(mine), 4) if mine else 0,
                     "avg_calls": round(sum(r.get("calls", 0) for r in mine) / len(mine), 1) if mine else 0})
    base = rows[0]["median_secs"] if rows and rows[0]["median_secs"] else None
    for row in rows:
        row["faster_than_first"] = (round(1 - row["median_secs"] / base, 2) if base and row["median_secs"] else None)
    return rows


def reference_solution_scores(base, task, cache):
    seed, fixed = cache / f"{task['id']}-seed", cache / f"{task['id']}-fixed"
    fresh_workdir(base, task, seed)
    overlay(task["dir"] / "accept", seed / "backend" / "src" / "__tests__" / "accept")
    seed_code = run(["npm", "test"], seed)[0]
    fresh_workdir(base, task, fixed)
    base_sha = run(["git", "rev-parse", "HEAD"], fixed)[1].strip()
    untouched = score(fixed, task, base_sha)
    shutil.rmtree(fixed / "backend" / "src" / "__tests__" / "accept", ignore_errors=True)
    overlay(task["dir"] / "solution", fixed)
    if task.get("solution_mount"):
        mount(fixed, task["solution_mount"])
    run(["git", "add", "-A"], fixed)
    run(["git", "commit", "-qm", "reference solution"], fixed)
    solved, why = score(fixed, task, base_sha)
    return seed_code, untouched, solved, why


def validate_task(base, task, cache):
    seed_code, untouched, solved, why = reference_solution_scores(base, task, cache)
    good = seed_code != 0 and untouched == (False, "no commit") and solved
    print(f"{'OK  ' if good else 'FAIL'} {task['id']}: seed tests {'fail' if seed_code != 0 else 'PASS (bad)'}, "
          f"untouched scores {untouched[1]!r}, reference solution {'passes' if solved else 'FAILS: ' + why}")
    return good


def validate():
    with tempfile.TemporaryDirectory() as tmp:
        base = prepare_base(Path(tmp))
        results = [validate_task(base, task, Path(tmp)) for task in load_tasks()]
    sys.exit(0 if all(results) else 1)


def print_run(r):
    print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['model']}  {r['task']}#{r['trial']}  {r.get('secs', '-')}s  "
          f"${r.get('cost', 0)}  {r.get('calls', 0)} calls  {'' if r['passed'] else r['reason'][:120]}", flush=True)


def print_rows(rows):
    print("\nmodel | passed | median s | vs first | avg cost | avg calls")
    for r in rows:
        vs = "-" if r["faster_than_first"] is None else f"{r['faster_than_first']:+.0%} faster"
        print(f"{r['model']} | {r['passed']}/{r['runs']} | {r['median_secs']} | {vs} | ${r['avg_cost']} | {r['avg_calls']}")


def run_jobs(jobs, workers):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(one_run, jobs):
            results.append(r)
            print_run(r)
    return results


def configured_models(profiles):
    default_model = ((profiles.get("roles") or {}).get("coder") or {}).get("model", "Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo")
    return [m for m in os.environ.get("MODELS", default_model).split(",") if m]


def main():
    if "--validate" in sys.argv:
        validate()
    profiles = config.load()
    base_url = ((profiles.get("provider") or {}).get("base_url")) or "https://api.deepinfra.com/v1/openai"
    models = configured_models(profiles)
    tasks = load_tasks(set(filter(None, os.environ.get("TASKS", "").split(","))))
    trials, workers, timeout_min = int(os.environ.get("TRIALS", "2")), int(os.environ.get("WORKERS", "3")), int(os.environ.get("TIMEOUT_MIN", "20"))
    root = Path(tempfile.mkdtemp(prefix="smoke-coder-"))
    base, prices, key = prepare_base(root), fetch_prices(), os.environ["DEEPINFRA_API_KEY"]
    jobs = [(m, t, i, base, root, key, base_url, timeout_min, prices) for m in models for t in tasks for i in range(1, trials + 1)]
    print(f"{len(jobs)} runs: {len(models)} model(s) x {len(tasks)} task(s) x {trials} trial(s), {workers} at a time", flush=True)
    results = run_jobs(jobs, workers)
    rows = summarize(results, models)
    print_rows(rows)
    Path("smoke-coder-results.json").write_text(json.dumps({"summary": rows, "runs": results}, indent=2), encoding="utf-8")
    if not os.environ.get("KEEP"):
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
