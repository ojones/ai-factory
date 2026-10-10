#!/usr/bin/env python3
"""Smoke screen for coder models (.wayfinder coder-speed, ticket 14).

Runs the real coder prompt (agents/prompts/coder.md, round 1) with a candidate model on a few small
tasks against a copy of the Starter Template, then scores the result with hidden acceptance tests the
coder never saw. A cheap screen: it is good at spotting a model that is broken, slow or sloppy, and
poor at separating two close ones (use agents/replay for that).

Score for one run = a commit exists, no protected Starter Template file changed, `npm run check`
passes, and `npm test` passes with the task's acceptance tests added.

  python3 agents/smoke-coder/run.py --validate    no model: prove each task's acceptance tests fail on the seed
                                                  and pass on its reference solution (needs npm)
  MODELS=a,b python3 agents/smoke-coder/run.py    run the screen (needs openhands and DEEPINFRA_API_KEY)

Candidates (from DeepInfra's /models list; each is faster or smaller than the 480B Qwen coder, tool-call and
cost fields unverified, so run the T1/T2 checks of agents/smoke/run.py with MODEL=<id> first):
  Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo (baseline)  deepseek-ai/DeepSeek-V4.1-Flash  Qwen/Qwen3.8-Flash
  zai-org/GLM-5.3-Flash  Qwen/Qwen3.5-35B-A3B  openai/gpt-oss-120b-Turbo  MiniMaxAI/MiniMax-M3

Env: MODELS (comma-separated DeepInfra ids; default the coder in agents/profiles.yml; the first is the
baseline the others' speed is compared with), TASKS (comma-separated ids, default all), TRIALS (per
model and task, default 2), WORKERS (default 3), TIMEOUT_MIN (per run, default 20), KEEP=1 (keep the
working directories). Writes smoke-coder-results.json.
"""
import json, os, re, shutil, statistics, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
import build_run as b  # noqa: E402

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
        return p.returncode, (p.stdout + p.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        return "timeout", ""


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
    """Wire a solution's router into app.ts: import after the health router's, use before the static files."""
    app = workdir / "backend" / "src" / "app.ts"
    text = app.read_text()
    text = text.replace('import { healthRouter } from "./routes/health";',
                        'import { healthRouter } from "./routes/health";\n' + spec["import"], 1)
    marker = "  // One container: the backend serves"
    text = text.replace(marker, f"  {spec['use']}\n\n" + marker, 1)
    app.write_text(text)


def prepare_base(cache):
    """The Starter Template with dependencies installed once; every trial starts from a copy."""
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
    """(passed, reason). Adds the hidden acceptance tests only now, after the coder is done."""
    count = run(["git", "rev-list", "--count", f"{base_sha}..HEAD"], workdir)[1].strip()
    if not count.isdigit() or int(count) == 0:
        return False, "no commit"
    changed = run(["git", "diff", "--name-only", f"{base_sha}..HEAD"], workdir)[1].split("\n")
    bad = b.protected_violations([c for c in changed if c])
    if bad:
        return False, f"changed protected files: {', '.join(bad)}"
    overlay(task["dir"] / "accept", workdir / "backend" / "src" / "__tests__" / "accept")
    code, out = run(["npm", "run", "check"], workdir)
    if code != 0:
        return False, f"type-check failed: {out[-300:]}"
    code, out = run(["npm", "test"], workdir)
    if code != 0:
        return False, f"tests failed: {out[-300:]}"
    return True, "ok"


def cost_of(state):
    metrics = (state.get("stats") or {}).get("usage_to_metrics") or {}
    return sum((m or {}).get("accumulated_cost") or 0 for m in metrics.values())


def one_run(job):
    model, task, trial, base, root, key, base_url, timeout_min = job
    workdir, home = root / f"{task['id']}-{trial}", root / f"home-{task['id']}-{trial}"
    result = {"model": model, "task": task["id"], "trial": trial}
    try:
        fresh_workdir(base, task, workdir)
        base_sha = run(["git", "rev-parse", "HEAD"], workdir)[1].strip()
        findings = root / f"findings-{task['id']}-{trial}.json"
        findings.write_text('{"blocking": [], "minor": []}')
        prompt = b.render(b.load_prompt(str(ROOT / "agents" / "prompts" / "coder.md")), {
            "app_name": "smoke-app", "round": "1", "task": task["task"], "findings_path": findings,
            "build_kind": task["build_kind"]})
        home.mkdir(parents=True, exist_ok=True)
        env = {**minimal_env(home), "LLM_MODEL": "openai/" + model, "LLM_BASE_URL": base_url, "LLM_API_KEY": key,
               "RUNTIME": "process"}
        began = time.time()
        try:
            rc = subprocess.run(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd=workdir,
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=timeout_min * 60).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
        result["secs"] = round(time.time() - began, 1)
        result["exit"] = rc
        usage, cost = None, 0.0
        for state_file in sorted((home / ".openhands" / "conversations").glob("*/base_state.json")):
            state = json.loads(state_file.read_text())
            usage, cost = b.summarize_token_usage(state), cost_of(state)
        result.update(calls=(usage or {}).get("calls", 0), llm_secs=(usage or {}).get("llm_seconds", 0),
                      peak_context=(usage or {}).get("peak_context", 0), cost=round(cost, 4))
        result["passed"], result["reason"] = (False, f"coder exited {rc}") if rc == "timeout" else score(workdir, task, base_sha)
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


def validate():
    """No model: each task's acceptance tests must fail on the seed and pass on the reference solution."""
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        base = prepare_base(cache)
        for task in load_tasks():
            seed, fixed = cache / f"{task['id']}-seed", cache / f"{task['id']}-fixed"
            fresh_workdir(base, task, seed)
            overlay(task["dir"] / "accept", seed / "backend" / "src" / "__tests__" / "accept")
            seed_code = run(["npm", "test"], seed)[0]
            fresh_workdir(base, task, fixed)
            base_sha = run(["git", "rev-parse", "HEAD"], fixed)[1].strip()
            # The scorer itself: an untouched checkout is "no commit"; a committed reference solution passes.
            untouched = score(fixed, task, base_sha)
            shutil.rmtree(fixed / "backend" / "src" / "__tests__" / "accept", ignore_errors=True)
            overlay(task["dir"] / "solution", fixed)
            if task.get("solution_mount"):
                mount(fixed, task["solution_mount"])
            run(["git", "add", "-A"], fixed)
            run(["git", "commit", "-qm", "reference solution"], fixed)
            solved, why = score(fixed, task, base_sha)
            good = seed_code != 0 and untouched == (False, "no commit") and solved
            ok &= good
            print(f"{'OK  ' if good else 'FAIL'} {task['id']}: seed tests {'fail' if seed_code != 0 else 'PASS (bad)'}, "
                  f"untouched scores {untouched[1]!r}, reference solution {'passes' if solved else 'FAILS: ' + why}")
    sys.exit(0 if ok else 1)


def main():
    if "--validate" in sys.argv:
        validate()
    key = os.environ["DEEPINFRA_API_KEY"]
    profiles = b.load_config() if hasattr(b, "load_config") else {}
    default_model = ((profiles.get("roles") or {}).get("coder") or {}).get("model", "Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo")
    base_url = ((profiles.get("provider") or {}).get("base_url")) or "https://api.deepinfra.com/v1/openai"
    models = [m for m in os.environ.get("MODELS", default_model).split(",") if m]
    only = set(filter(None, os.environ.get("TASKS", "").split(",")))
    trials, workers = int(os.environ.get("TRIALS", "2")), int(os.environ.get("WORKERS", "3"))
    timeout_min = int(os.environ.get("TIMEOUT_MIN", "20"))
    tasks = load_tasks(only)
    root = Path(tempfile.mkdtemp(prefix="smoke-coder-"))
    base = prepare_base(root)
    jobs = [(m, t, i, base, root, key, base_url, timeout_min) for m in models for t in tasks for i in range(1, trials + 1)]
    print(f"{len(jobs)} runs: {len(models)} model(s) x {len(tasks)} task(s) x {trials} trial(s), {workers} at a time", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(one_run, jobs):
            results.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['model']}  {r['task']}#{r['trial']}  {r.get('secs', '-')}s  "
                  f"${r.get('cost', 0)}  {r.get('calls', 0)} calls  {'' if r['passed'] else r['reason'][:120]}", flush=True)
    rows = summarize(results, models)
    print("\nmodel | passed | median s | vs first | avg cost | avg calls")
    for r in rows:
        vs = "-" if r["faster_than_first"] is None else f"{r['faster_than_first']:+.0%} faster"
        print(f"{r['model']} | {r['passed']}/{r['runs']} | {r['median_secs']} | {vs} | ${r['avg_cost']} | {r['avg_calls']}")
    Path("smoke-coder-results.json").write_text(json.dumps({"summary": rows, "runs": results}, indent=2))
    if not os.environ.get("KEEP"):
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
