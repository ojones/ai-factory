#!/usr/bin/env python3
"""Replay the reviewer over commits from real Build Runs (issue #41).

Re-runs only the review step against commits the Managed App repos still hold, with the
current prompts and model, and sets the result beside what the reviewer concluded at the time.
Minutes and cents, instead of a 90-minute, $2 Build Run.

MODE=single  one model call over a prompt the Orchestrator assembles (the Build Run's default)
MODE=agent   the exploring OpenHands reviewer (what the Build Run used before)

Env: DEEPINFRA_API_KEY, MODE, MODEL (default: the reviewer's model in agents/profiles.yml),
CASES (comma-separated ids, default all), WORKERS (default 4), OWNER (default ojones).
Prints per-case time, tokens and verdicts; writes replay-results.json.
"""
import json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "orchestrator"))
import build_run as b  # noqa: E402

KEY = os.environ["DEEPINFRA_API_KEY"]
MODE = os.environ.get("MODE", "single")
OWNER = os.environ.get("OWNER", "ojones")
WORKERS = int(os.environ.get("WORKERS", "4"))
cfg = b.load_config()
MODEL = os.environ.get("MODEL") or cfg["roles"]["reviewer"]["model"]
BASE_URL = cfg["provider"]["base_url"]
MAX_CHARS = cfg["limits"].get("review_context_max_chars", 200000)
cases = json.loads((HERE / "cases.json").read_text())["cases"]
if os.environ.get("CASES"):
    wanted = set(os.environ["CASES"].split(","))
    cases = [c for c in cases if c["id"] in wanted]

work = Path(tempfile.mkdtemp(prefix="replay-"))
clones = {}
for app in sorted({c["app"] for c in cases}):
    clones[app] = work / app
    subprocess.run(["git", "clone", "-q", f"https://github.com/{OWNER}/{app}.git", str(clones[app])], check=True)


def git_in(repo):
    def run(*args):
        p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
        return p.stdout if p.returncode == 0 else ""
    return run


def single(case):
    repo = clones[case["app"]]
    ctx = b.build_review_context(git_in(repo), case["base"], case["head"], MAX_CHARS)
    system = b.render(b.load_prompt(cfg["roles"]["reviewer"]["fast_prompt"]),
                      {"app_name": case["app"], "base_sha": case["base"][:8], "head_sha": case["head"][:8]})
    doc, usage = b.single_call_review(BASE_URL, KEY, MODEL, system, ctx)
    return doc, {"prompt_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
                 "cost": usage.get("estimated_cost") or 0}


def agent(case):
    repo = clones[case["app"]]
    tree = work / f"tree-{case['id']}"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(tree), case["head"]], cwd=repo, check=True)
    home = work / f"home-{case['id']}"
    home.mkdir()
    verdict = work / f"verdict-{case['id']}.json"
    prompt = b.render(b.load_prompt(cfg["roles"]["reviewer"]["prompt"]),
                      {"app_name": case["app"], "base_sha": case["base"], "head_sha": case["head"], "verdict_path": verdict})
    env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR", "CI") if k in os.environ}
    env.update({"HOME": str(home), "LLM_MODEL": "openai/" + MODEL, "LLM_BASE_URL": BASE_URL, "LLM_API_KEY": KEY, "RUNTIME": "process"})
    log = work / f"agent-{case['id']}.jsonl"
    with log.open("w") as f:
        subprocess.run(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd=tree, env=env,
                       stdout=f, stderr=subprocess.STDOUT, timeout=45 * 60)
    doc = json.loads(verdict.read_text())
    out_tokens = calls = 0
    for state in home.glob(".openhands/conversations/*/base_state.json"):
        u = b.summarize_token_usage(json.loads(state.read_text()))
        out_tokens, calls = u["completion_tokens"], u["calls"]
    return doc, {"output_tokens": out_tokens, "calls": calls}


def run(case):
    start = time.time()
    try:
        doc, stats = (single if MODE == "single" else agent)(case)
        clean, blocking, minor = b.derive_review(doc)
        return {"id": case["id"], "secs": round(time.time() - start), **stats, "clean": clean,
                "blocking": [f["summary"] for f in blocking], "minor": [f["summary"] for f in minor],
                "recorded": case["recorded"]}
    except Exception as e:  # noqa: BLE001
        return {"id": case["id"], "secs": round(time.time() - start), "error": f"{type(e).__name__}: {e}", "recorded": case["recorded"]}


with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    results = list(pool.map(run, cases))

print(f"MODE={MODE} MODEL={MODEL}\n")
agree = 0
for r in results:
    rec = r["recorded"]
    if "error" in r:
        print(f"{r['id']}: ERROR after {r['secs']}s: {r['error']}\n")
        continue
    same = r["clean"] == (rec["verdict"] == "clean")
    agree += same
    print(f"{r['id']}: {r['secs']}s, {r.get('prompt_tokens', '-')} prompt / {r['output_tokens']} output tokens"
          f"{', ' + str(r['calls']) + ' calls' if 'calls' in r else ''}")
    print(f"  recorded: {rec['verdict']}, {len(rec['blocking'])} blocking | now: {'clean' if r['clean'] else 'changes_requested'}, "
          f"{len(r['blocking'])} blocking  -> verdict {'agrees' if same else 'DIFFERS'}")
    for s in rec["blocking"]:
        print(f"    recorded blocking: {s[:140]}")
    for s in r["blocking"]:
        print(f"    now blocking:      {s[:140]}")
    print()
ok = [r for r in results if "error" not in r]
if ok:
    print(f"verdict agreement {agree}/{len(ok)}; average {sum(r['secs'] for r in ok) / len(ok):.0f}s, "
          f"{sum(r['output_tokens'] for r in ok) // len(ok)} output tokens; "
          f"total cost ${sum(r.get('cost', 0) for r in ok):.4f}" + ("" if MODE == "single" else " (agent cost not summed)"))
Path("replay-results.json").write_text(json.dumps(results, indent=1))
