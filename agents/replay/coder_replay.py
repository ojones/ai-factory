#!/usr/bin/env python3
"""Replay the coder over the recorded Managed Apps' real tasks (.wayfinder coder-speed, ticket 15).

The recorded apps' histories are kept as bundles beside this script (data/). Each app's base commit is
the seed repository whose INTAKE.md Spec is the task the coder was given. For each model and task, this
checks out the base, runs the real coder prompt (round 1), then scores the result the way a Build Run
would judge it:

  built     a commit exists, no protected Starter Template file changed, `npm run build` and `npm test` pass
  clean     the production single-call reviewer (agents/profiles.yml) finds no blocking issue in the diff

A run that is built and clean would have needed no further review round, so `ok` (both) is the figure
that predicts speed: a model that is fast per round but misses often costs extra rounds.

  MODELS=a,b REPEAT=3 python3 agents/replay/coder_replay.py

Env: DEEPINFRA_API_KEY, MODELS (comma-separated; the first is the baseline), APPS (default all apps in
cases.json), REPEAT (runs per model and task, default 2), WORKERS (default 3), TIMEOUT_MIN (default 25),
KEEP=1. Writes coder-replay-results.json.
"""
import importlib.util, json, os, re, shutil, statistics, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
import build_run as b  # noqa: E402

_spec = importlib.util.spec_from_file_location("smoke_coder", ROOT / "agents" / "smoke-coder" / "run.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

KEY = os.environ["DEEPINFRA_API_KEY"]
cfg = b.load_config()
BASE_URL = cfg["provider"]["base_url"]
REVIEWER = cfg["roles"]["reviewer"]
MAX_CHARS = cfg["limits"].get("review_context_max_chars", 200000)
MODELS = [m for m in os.environ.get("MODELS", cfg["roles"]["coder"]["model"]).split(",") if m]
REPEAT, WORKERS = int(os.environ.get("REPEAT", "2")), int(os.environ.get("WORKERS", "3"))
TIMEOUT_MIN = int(os.environ.get("TIMEOUT_MIN", "25"))


def git(repo, *args):
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def spec_of(intake):
    m = re.search(r"## Spec\s*\n(.*?)(?=\n## |\Z)", intake, re.S)
    return (m.group(1) if m else intake).strip()


def prepare(app, base_sha, root):
    """The app at its base commit with dependencies installed once; every run starts from a copy."""
    bundle = HERE / "data" / f"{app}.bundle"
    source = str(bundle) if bundle.exists() else f"https://github.com/ojones/{app}.git"
    prep = root / f"prep-{app}"
    subprocess.run(["git", "clone", "-q", source, str(prep)], check=True)
    git(prep, "checkout", "-q", "-B", "main", base_sha)
    for k, v in (("user.email", "replay@ai-factory.local"), ("user.name", "replay")):
        git(prep, "config", k, v)
    code, out = smoke.run(["npm", "ci", "--no-audit", "--no-fund"], prep, timeout=900)
    if code != 0:
        sys.exit(f"npm ci failed for {app}: {out[-400:]}")
    return prep, spec_of((prep / "INTAKE.md").read_text())


def review(workdir, base, head, build_kind):
    try:
        ctx = b.build_review_context(lambda *a: git(workdir, *a), base, head, MAX_CHARS)
    except b.ContextTooLarge:
        return None, "review skipped: diff too large for one call"
    system = b.render(b.load_prompt(REVIEWER["fast_prompt"]),
                      {"app_name": "replay", "build_kind": build_kind, "base_sha": base[:8], "head_sha": head[:8]})
    doc, _ = b.single_call_review(BASE_URL, KEY, REVIEWER["model"], system, ctx)
    _, blocking, _ = b.derive_review(doc)
    return [f["summary"] for f in blocking], ""


def one_run(job):
    model, app, trial, prep, task, base_sha, root, timeout_min, prices = job
    slug = re.sub(r"[^A-Za-z0-9]+", "-", model).strip("-")
    workdir, home = root / f"{slug}-{app}-{trial}", root / f"home-{slug}-{app}-{trial}"
    result = {"model": model, "app": app, "trial": trial}
    try:
        shutil.copytree(prep, workdir, symlinks=True)
        findings = root / f"findings-{slug}-{app}-{trial}.json"
        findings.write_text('{"blocking": [], "minor": []}')
        prompt = b.render(b.load_prompt(str(ROOT / "agents" / "prompts" / "coder.md")), {
            "app_name": app, "round": "1", "task": task, "findings_path": findings, "build_kind": "first build"})
        home.mkdir(parents=True, exist_ok=True)
        env = {**smoke.minimal_env(home), "LLM_MODEL": "openai/" + model, "LLM_BASE_URL": BASE_URL, "LLM_API_KEY": KEY,
               "RUNTIME": "process"}
        began = time.time()
        try:
            rc = subprocess.run(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd=workdir,
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=timeout_min * 60).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
        result["secs"], result["exit"] = round(time.time() - began, 1), rc
        usage, cost = None, 0.0
        for state_file in sorted((home / ".openhands" / "conversations").glob("*/base_state.json")):
            state = json.loads(state_file.read_text())
            usage, cost = b.summarize_token_usage(state), smoke.cost_of(state, prices.get(model, {}))
        result.update(calls=(usage or {}).get("calls", 0), llm_secs=(usage or {}).get("llm_seconds", 0),
                      peak_context=(usage or {}).get("peak_context", 0), cost=round(cost, 4))
        head = git(workdir, "rev-parse", "HEAD").strip()
        bad = b.protected_violations([c for c in git(workdir, "diff", "--name-only", f"{base_sha}..{head}").split("\n") if c])
        if rc == "timeout":
            result.update(built=False, clean=False, reason="coder timed out")
        elif head == base_sha:
            result.update(built=False, clean=False, reason="no commit")
        elif bad:
            result.update(built=False, clean=False, reason=f"changed protected files: {', '.join(bad)}")
        else:
            code_b, out_b = smoke.run(["npm", "run", "build"], workdir)
            code_t, out_t = smoke.run(["npm", "test"], workdir) if code_b == 0 else (None, "")
            result["built"] = code_b == 0 and code_t == 0
            result["reason"] = "" if result["built"] else smoke.digest(out_b if code_b != 0 else out_t)
            blocking, note = review(workdir, base_sha, head, "first build")
            result["blocking"] = blocking
            result["clean"] = blocking is not None and not blocking
            if note:
                result["reason"] = (result["reason"] + " " + note).strip()
        result["ok"] = bool(result.get("built") and result.get("clean"))
    except Exception as e:  # noqa: BLE001 - a broken run is a result, not a crash of the replay
        result.update(built=False, clean=False, ok=False, reason=f"harness error: {type(e).__name__}: {e}")
    return result


def main():
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    wanted = set(filter(None, os.environ.get("APPS", "").split(",")))
    apps = {}
    for c in cases:
        if not wanted or c["app"] in wanted:
            apps.setdefault(c["app"], c["base"])
    root = Path(tempfile.mkdtemp(prefix="coder-replay-"))
    preps = {app: prepare(app, base, root) for app, base in apps.items()}
    prices = smoke.fetch_prices()
    jobs = [(m, app, i, preps[app][0], preps[app][1], apps[app], root, TIMEOUT_MIN, prices)
            for m in MODELS for app in apps for i in range(1, REPEAT + 1)]
    print(f"{len(jobs)} runs: {len(MODELS)} model(s) x {len(apps)} task(s) x {REPEAT}, {WORKERS} at a time", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for r in pool.map(one_run, jobs):
            results.append(r)
            flag = "OK  " if r["ok"] else ("BUILT" if r.get("built") else "FAIL")
            print(f"{flag} {r['model'].split('/')[-1]}  {r['app']}#{r['trial']}  {r.get('secs', '-')}s  ${r.get('cost', 0)}  "
                  f"{r.get('calls', 0)} calls  blocking={len(r['blocking']) if r.get('blocking') is not None else '-'}  "
                  f"{r.get('reason', '')[:160]}", flush=True)
    print("\nmodel | ok (built+clean) | built | median s | model s | avg cost | avg calls | avg blocking")
    summary = []
    for m in MODELS:
        rs = [r for r in results if r["model"] == m]
        blocks = [len(r["blocking"]) for r in rs if r.get("blocking") is not None]
        row = {"model": m, "runs": len(rs), "ok": sum(r["ok"] for r in rs), "built": sum(bool(r.get("built")) for r in rs),
               "median_secs": statistics.median([r["secs"] for r in rs if "secs" in r] or [0]),
               "median_llm_secs": statistics.median([r.get("llm_secs", 0) for r in rs] or [0]),
               "avg_cost": round(sum(r.get("cost", 0) for r in rs) / max(len(rs), 1), 4),
               "avg_calls": round(sum(r.get("calls", 0) for r in rs) / max(len(rs), 1), 1),
               "avg_blocking": round(sum(blocks) / len(blocks), 2) if blocks else None}
        summary.append(row)
        print(f"{m} | {row['ok']}/{row['runs']} | {row['built']}/{row['runs']} | {row['median_secs']} | {row['median_llm_secs']} | "
              f"${row['avg_cost']} | {row['avg_calls']} | {row['avg_blocking']}")
    Path("coder-replay-results.json").write_text(json.dumps({"summary": summary, "runs": results}, indent=2))
    if not os.environ.get("KEEP"):
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
