#!/usr/bin/env python3
"""Whole-run benchmark: is a candidate model (or prompt) as good as the current one, and what does it save?

The Factory swaps models as better, cheaper, faster or more specialised ones appear. A swap is only safe if it is measured on the real thing,
the whole Build Run, not on one role in isolation. This runs a fixed SUITE of Intakes (agents/benchmark/suite.json) through the real Build Run
workflow against one disposable bench app, resets that app to a frozen commit before every task, and scores each task with an ORACLE: `api_check`
scenarios run against the deployed app, plus the outcome the task expects. Code decides pass or fail, never a model. The result is compared with
the accepted BASELINE (agents/benchmark/baseline.json) under fixed RULES (agents/benchmark/rules.json), and the report says whether to accept the
candidate and how much cost and time it saves.

  python3 orchestrator/benchmark.py plan   [--candidate coder=ID,tester=ID] [--tasks a,b]    what a pass would do and cost (no spend)
  python3 orchestrator/benchmark.py run    --label NAME [--candidate ...] [--tasks ...] [--execute]   a pass (without --execute it only prints the plan)
  python3 orchestrator/benchmark.py compare RESULT.json                                       compare a result with the baseline
  python3 orchestrator/benchmark.py accept  RESULT.json                                       make a result the new baseline
  python3 orchestrator/benchmark.py freeze                                                    record the bench app's current main as the frozen base

A candidate is a branch whose agents/profiles.yml names the candidate models; the runner dispatches the real `build-run.yml` from that branch, so
production code carries no "benchmark mode". The branch also pins the limits that would make passes incomparable (no flag retirement
ride-along, a short watchdog, no daily cap). See docs/benchmark-protocol.md.
"""
import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "agents" / "benchmark" / "suite.json"
RULES = ROOT / "agents" / "benchmark" / "rules.json"
BASELINE = ROOT / "agents" / "benchmark" / "baseline.json"
ROLES = ("coder", "tester", "reviewer", "planner", "pipeline", "retrospective")
BENCH_LIMITS = {"flag_retirement": {"min_age_days": 1, "piggyback_max": 0}, "watchdog_minutes": 2, "daily_cost_cap_usd": 0}
DEFAULT_RULES = {"max_pass_drop": 1, "max_cost_ratio": 1.3, "max_rounds_delta": 0.5, "must_pass_tags": ["refusal", "safety"], "improvement_ratio": 0.9}


# --- pure logic (unit-tested) -------------------------------------------------


def parse_candidate(text):
    """{role: model} from 'coder=a/b,tester=c/d'. A blank string means the current profile (a baseline pass). Raises ValueError for a bad pair."""
    out = {}
    for pair in [p.strip() for p in (text or "").split(",") if p.strip()]:
        role, _, model = pair.partition("=")
        if role not in ROLES or not re.fullmatch(r"[\w./:-]+", model or ""):
            raise ValueError(f"bad candidate pair {pair!r}: use role=model-id with a role in {', '.join(ROLES)}")
        out[role] = model
    return out


def candidate_profile(profile_text, overrides):
    """The profiles.yml text for a pass: the given roles switched to the candidate models, and the limits that keep passes comparable."""
    doc = yaml.safe_load(profile_text)
    for role, model in overrides.items():
        if role not in doc.get("roles", {}):
            raise ValueError(f"profiles.yml has no role {role!r}")
        doc["roles"][role]["model"] = model
        doc["roles"][role].pop("fix_model", None) if role == "coder" else None
    limits = doc.setdefault("limits", {})
    for key, value in BENCH_LIMITS.items():
        limits[key] = value
    return yaml.safe_dump(doc, sort_keys=False)


def validate_suite(suite):
    """Problems with a suite file (empty means usable)."""
    problems, seen = [], set()
    tasks = suite.get("tasks") if isinstance(suite, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return ["the suite has no tasks"]
    for t in tasks:
        tid = t.get("id") if isinstance(t, dict) else None
        if not isinstance(tid, str) or not tid or tid in seen:
            problems.append(f"task {tid!r} needs a unique id")
            continue
        seen.add(tid)
        if not t.get("request"):
            problems.append(f"{tid}: no request")
        outcomes = (t.get("expected") or {}).get("outcomes")
        if not isinstance(outcomes, list) or not outcomes:
            problems.append(f"{tid}: expected.outcomes is required")
        if not isinstance(t.get("oracle", {}).get("checks"), list):
            problems.append(f"{tid}: oracle.checks must be a list (empty for a task that must be refused)")
        ids = [c.get("id") for c in t.get("oracle", {}).get("checks", []) + t.get("setup", [])]
        if len(ids) != len(set(ids)):
            problems.append(f"{tid}: duplicate oracle or setup check ids")
    return problems


def fill_request(request, pass_id):
    return request.replace("{pass}", pass_id)


def select_tasks(suite, names):
    tasks = suite["tasks"]
    if not names:
        return tasks
    wanted = [n.strip() for n in names.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in {t["id"] for t in tasks}]
    if unknown:
        raise ValueError(f"unknown task(s): {', '.join(unknown)}")
    return [t for t in tasks if t["id"] in wanted]


def score_task(task, report, oracle_results):
    """One task's score from its Build Run Report (state.json) and the oracle's results. The outcome must be one the task expects, the cost must
    stay under any `max_cost` it sets, and every oracle check must pass: nothing here asks a model."""
    outcome = (report or {}).get("outcome")
    expected = task.get("expected") or {}
    cost = float((report or {}).get("spent_usd") or 0)
    outcome_ok = outcome in expected.get("outcomes", [])
    cost_ok = "max_cost" not in expected or cost <= float(expected["max_cost"])
    failed = [r.get("id") for r in oracle_results if not r.get("ok")]
    started, finished = (report or {}).get("started_at"), (report or {}).get("finished_at")
    return {"id": task["id"], "tags": task.get("tags", []), "outcome": outcome, "outcome_ok": outcome_ok, "cost_ok": cost_ok,
            "oracle_failed": failed, "oracle_ok": not failed, "passed": bool(outcome_ok and cost_ok and not failed and report is not None),
            "cost_usd": round(cost, 4), "rounds": int((report or {}).get("review_passes") or 0), "minutes": minutes_between(started, finished)}


def minutes_between(a, b):
    """Minutes between two ISO timestamps, or None if either cannot be read."""
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        return round((time.mktime(time.strptime(b[:19], fmt)) - time.mktime(time.strptime(a[:19], fmt))) / 60, 1)
    except (TypeError, ValueError):
        return None


def aggregate(scores):
    """Totals over a pass: how many tasks passed, total cost and time, mean rounds of the tasks that ran Agents, and the failures by task."""
    n = len(scores)
    ran = [s for s in scores if s["rounds"]]
    minutes = [s["minutes"] for s in scores if s["minutes"] is not None]
    return {"tasks": n, "passed": sum(s["passed"] for s in scores), "cost_usd": round(sum(s["cost_usd"] for s in scores), 4),
            "minutes": round(sum(minutes), 1), "rounds_mean": round(sum(s["rounds"] for s in ran) / len(ran), 2) if ran else 0.0,
            "failed": [s["id"] for s in scores if not s["passed"]], "by_task": {s["id"]: s for s in scores}}


def compare(candidate, baseline, rules=None):
    """{accept, reasons, deltas, improvement} for a candidate pass against the accepted baseline under the rules. The candidate is accepted only
    if its pass count is within `max_pass_drop` of the baseline's, every task tagged in `must_pass_tags` that passed in the baseline still passes,
    its cost is within `max_cost_ratio` times the baseline's and its mean rounds rise by at most `max_rounds_delta`. A faster or cheaper candidate
    that stays inside those bounds is reported as an improvement."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    reasons = []
    drop = baseline["passed"] - candidate["passed"]
    if drop > rules["max_pass_drop"]:
        reasons.append(f"passes {candidate['passed']} of {candidate['tasks']}, {drop} fewer than the baseline's {baseline['passed']} (allowed: {rules['max_pass_drop']})")
    for tid, base in baseline.get("by_task", {}).items():
        now = candidate.get("by_task", {}).get(tid)
        if base.get("passed") and now is not None and not now.get("passed") and set(base.get("tags", [])) & set(rules["must_pass_tags"]):
            reasons.append(f"{tid} ({', '.join(base['tags'])}) passed in the baseline and failed now: {now.get('outcome')}")
    cost_ratio = candidate["cost_usd"] / baseline["cost_usd"] if baseline["cost_usd"] else 1.0
    if cost_ratio > rules["max_cost_ratio"]:
        reasons.append(f"cost ${candidate['cost_usd']:.2f} is {cost_ratio:.2f}x the baseline's ${baseline['cost_usd']:.2f} (allowed: {rules['max_cost_ratio']}x)")
    rounds_delta = candidate["rounds_mean"] - baseline["rounds_mean"]
    if rounds_delta > rules["max_rounds_delta"]:
        reasons.append(f"rounds per run rose by {rounds_delta:.2f} (allowed: {rules['max_rounds_delta']})")
    minutes_ratio = candidate["minutes"] / baseline["minutes"] if baseline["minutes"] else 1.0
    accept = not reasons
    better = cost_ratio <= rules["improvement_ratio"] or minutes_ratio <= rules["improvement_ratio"]
    return {"accept": accept, "reasons": reasons, "improvement": bool(accept and better),
            "deltas": {"passed": candidate["passed"] - baseline["passed"], "cost_ratio": round(cost_ratio, 2), "minutes_ratio": round(minutes_ratio, 2),
                       "rounds_delta": round(rounds_delta, 2)}}


def render_report(label, candidate_models, agg, verdict=None):
    lines = [f"# Benchmark `{label}`", "", f"Candidate: {', '.join(f'{r}={m}' for r, m in candidate_models.items()) or 'the current profile (a baseline pass)'}", "",
             f"**{agg['passed']} of {agg['tasks']} tasks passed**, ${agg['cost_usd']:.2f}, {agg['minutes']:.0f} minutes, {agg['rounds_mean']:.2f} review rounds per run.", ""]
    if verdict:
        d = verdict["deltas"]
        lines += [f"**{'ACCEPT' if verdict['accept'] else 'REJECT'}** against the baseline: passes {d['passed']:+d}, cost {d['cost_ratio']}x, time {d['minutes_ratio']}x, "
                  f"rounds {d['rounds_delta']:+}." + (" This is an improvement: it saves cost or time without losing quality." if verdict["improvement"] else "")]
        lines += [f"- {r}" for r in verdict["reasons"]] + [""]
    lines += ["| Task | Outcome | Pass | Cost | Rounds | Minutes | Oracle failures |", "|---|---|---|---|---|---|---|"]
    for s in agg["by_task"].values():
        lines.append(f"| {s['id']} | {s['outcome']} | {'yes' if s['passed'] else 'NO'} | ${s['cost_usd']:.3f} | {s['rounds']} | {s['minutes'] if s['minutes'] is not None else '-'} | "
                     f"{', '.join(s['oracle_failed']) or '-'} |")
    return "\n".join(lines) + "\n"


def estimate(tasks):
    """A rough price and duration for a pass, from what real runs have cost ($0.1 to $0.6 and 16 to 35 minutes an update run, a refusal about nothing)."""
    ran = [t for t in tasks if "refusal" not in t.get("tags", [])]
    return {"runs": len(ran), "refusals": len(tasks) - len(ran), "cost_low": round(0.12 * len(ran), 2), "cost_high": round(0.6 * len(ran) + 0.1 * (len(tasks) - len(ran)), 2),
            "hours_low": round(0.27 * len(ran), 1), "hours_high": round(0.6 * len(ran), 1)}


# --- the runner: GitHub, git and the deployed bench app (not unit-tested; `plan` is a dry run) ---------------------------------------------------

def _env():
    import os
    return os.environ


def gh(args, token=None, check=True):
    import os
    import subprocess
    p = subprocess.run(["gh", *args], capture_output=True, text=True, env={**os.environ, "GH_TOKEN": token or os.environ["FACTORY_PAT"]})
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {(p.stderr or p.stdout)[-300:]}")
    return p.stdout


def publish_branch(repo, branch, profile_text):
    """Create `branch` from main with agents/profiles.yml replaced by `profile_text` (through the API, so no local checkout is needed)."""
    import base64
    sha = gh(["api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"]).strip()
    gh(["api", "-X", "POST", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}"])
    file_sha = gh(["api", f"repos/{repo}/contents/agents/profiles.yml?ref={branch}", "--jq", ".sha"]).strip()
    gh(["api", "-X", "PUT", f"repos/{repo}/contents/agents/profiles.yml", "-f", f"message=Benchmark candidate profile for {branch}", "-f", f"branch={branch}",
        "-f", f"sha={file_sha}", "-f", "content=" + base64.b64encode(profile_text.encode()).decode()])


def delete_branch(repo, branch):
    gh(["api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{branch}"], check=False)


def reset_bench(owner, app, base_sha):
    """Force the bench app's main back to the frozen commit, and wait for that commit's deploy if main moved (an older deploy finishing
    after a newer one would put the app back). Returns True if main moved."""
    import os
    import subprocess
    import tempfile
    sys.path.insert(0, str(Path(__file__).parent))
    import build_run as b
    header = "Authorization: Basic " + __import__("base64").b64encode(f"x-access-token:{os.environ['FACTORY_PAT']}".encode()).decode()
    env = {**os.environ, **b.git_auth_env(header)}
    work = tempfile.mkdtemp(prefix="bench-")
    url = f"https://github.com/{owner}/{app}.git"
    subprocess.run(["git", "clone", "-q", "--no-checkout", url, work], env=env, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "origin/main"], cwd=work, capture_output=True, text=True).stdout.strip()
    if head == base_sha:
        return False
    subprocess.run(["git", "push", "-q", "--force", "origin", f"{base_sha}:refs/heads/main"], cwd=work, env=env, check=True, capture_output=True)
    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        runs = json.loads(gh(["run", "list", "--repo", f"{owner}/{app}", "--workflow", "deploy-fly.yml", "--limit", "10", "--json", "headSha,status,conclusion"], check=False) or "[]")
        mine = [r for r in runs if r["headSha"] == base_sha]
        if mine and all(r["status"] == "completed" for r in mine) and any(r["conclusion"] == "success" for r in mine):
            return True
        time.sleep(20)
    return True


def file_task_issue(repo, app, pass_id, task):
    import os
    import fixrequest
    import update_intake
    token = os.environ["FACTORY_PAT"]
    for label in (update_intake.FORM_LABEL, f"app:{app}", "benchmark"):
        update_intake.ensure_label(repo, label, token, "ededed", "Benchmark pass")
    body = fixrequest.intake_form(app, fill_request(task["request"], pass_id), f"{task.get('cost_cap', 1.0):.2f}")
    out = gh(["issue", "create", "--repo", repo, "--title", f"bench {pass_id}: {task['id']}", "--label", f"{update_intake.FORM_LABEL},app:{app},benchmark", "--body", body])
    return re.search(r"/issues/(\d+)", out).group(1)


def dispatch_and_wait(repo, app, branch, issue, timeout_min=75):
    """Dispatch the real Build Run workflow from the candidate branch and wait for it. Returns the run id."""
    t0 = time.time() - 5
    gh(["workflow", "run", "build-run.yml", "--repo", repo, "--ref", branch, "-f", f"issue_number={issue}", "-f", f"app_name={app}"])
    run_id, deadline = None, time.time() + timeout_min * 60
    while time.time() < deadline:
        runs = json.loads(gh(["run", "list", "--repo", repo, "--workflow", "build-run.yml", "--branch", branch, "--limit", "5", "--json", "databaseId,status,createdAt"], check=False) or "[]")
        if run_id is None and runs:
            run_id = runs[0]["databaseId"]
        mine = [r for r in runs if r["databaseId"] == run_id]
        if mine and mine[0]["status"] == "completed":
            return run_id
        time.sleep(30)
    return run_id


def read_report(repo, run_id):
    import glob
    import tempfile
    d = tempfile.mkdtemp(prefix="bench-report-")
    gh(["run", "download", str(run_id), "--repo", repo, "-n", "build-run", "-D", d], check=False)
    found = glob.glob(d + "/**/state.json", recursive=True)
    return json.load(open(found[0])) if found else None


def run_oracle(app, task):
    """The task's setup checks, then its oracle checks, through api_check against the deployed bench app."""
    import os
    sys.path.insert(0, str(Path(__file__).parent))
    import api_check
    import build_run as b
    checks = list(task.get("setup", [])) + list(task.get("oracle", {}).get("checks", []))
    if not checks:
        return []
    token = b.preview_token(os.environ["PREVIEW_MASTER_SECRET"], app)
    results = api_check.run_checks(checks, f"https://{app}.fly.dev", token)
    setup_ids = {c["id"] for c in task.get("setup", [])}
    return [r for r in results if r["id"] not in setup_ids or not r.get("ok")]


def archive_bench_flags(app, keep=("bench-seed",)):
    """Archive the features a pass created (GrowthBook cannot delete one), so a later pass starts clean. Best effort."""
    import os
    sys.path.insert(0, str(Path(__file__).parent))
    import build_run as b
    status, r = b.http("GET", f"{b.GROWTHBOOK_API}/features?limit=500", os.environ["GROWTHBOOK_ADMIN_PAT"])
    for f in (r.get("features") or []) if isinstance(r, dict) else []:
        fid = f.get("id", "")
        if fid.startswith(f"{app}.feature.") and fid.split(".feature.")[-1] not in keep and not f.get("archived"):
            b.http("POST", f"{b.GROWTHBOOK_API}/features/{fid}", os.environ["GROWTHBOOK_ADMIN_PAT"], {"archived": True})


def run_pass(label, overrides, task_names, execute):
    import os
    suite = json.load(open(SUITE))
    problems = validate_suite(suite)
    if problems:
        print("suite problems:\n- " + "\n- ".join(problems))
        return 2
    tasks = select_tasks(suite, task_names)
    est = estimate(tasks)
    print(f"Pass '{label}': {len(tasks)} task(s) on {suite['app']}: {', '.join(t['id'] for t in tasks)}")
    print(f"Candidate: {', '.join(f'{r}={m}' for r, m in overrides.items()) or 'current profile (baseline pass)'}")
    print(f"Estimate: ${est['cost_low']} to ${est['cost_high']}, {est['hours_low']} to {est['hours_high']} hours ({est['runs']} Build Runs, {est['refusals']} refusals).")
    if not execute:
        print("Dry run: nothing was started. Add --execute to spend it.")
        return 0
    if not suite.get("base_sha"):
        print("suite.json has no base_sha: stage and seed the bench app, then run `benchmark.py freeze` (docs/benchmark-protocol.md).")
        return 2
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, app = repo.split("/")[0], suite["app"]
    pass_id = time.strftime("%m%d%H%M", time.gmtime())
    branch = f"bench/{re.sub(r'[^a-z0-9-]', '-', label.lower())}-{pass_id}"
    publish_branch(repo, branch, candidate_profile((ROOT / "agents" / "profiles.yml").read_text(), overrides))
    scores = []
    try:
        for task in tasks:
            reset_bench(owner, app, suite["base_sha"])
            issue = file_task_issue(repo, app, pass_id, task)
            run_id = dispatch_and_wait(repo, app, branch, issue)
            report = read_report(repo, run_id) if run_id else None
            oracle = run_oracle(app, task) if report and report.get("outcome") in ("released", "nothing_to_release") else []
            score = score_task(task, report, oracle)
            scores.append(score)
            print(f"{task['id']}: {'PASS' if score['passed'] else 'FAIL'} ({score['outcome']}, ${score['cost_usd']:.3f}, {score['rounds']} rounds)", flush=True)
    finally:
        delete_branch(repo, branch)
        archive_bench_flags(app)
        reset_bench(owner, app, suite["base_sha"])
    agg = aggregate(scores)
    base = json.load(open(BASELINE)) if BASELINE.exists() else None
    verdict = compare(agg, base["aggregate"], json.load(open(RULES))) if base else None
    out = {"label": label, "candidate": overrides, "pass_id": pass_id, "aggregate": agg, "verdict": verdict}
    Path(f"benchmark-result-{label}.json").write_text(json.dumps(out, indent=2))
    report_md = render_report(label, overrides, agg, verdict)
    Path(f"benchmark-result-{label}.md").write_text(report_md)
    print(report_md)
    return 0


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="benchmark.py")
    ap.add_argument("command", choices=["plan", "run", "compare", "accept", "freeze"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--candidate", default="")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args(argv[1:])
    try:
        overrides = parse_candidate(a.candidate)
        if a.command in ("plan", "run"):
            return run_pass(a.label, overrides, a.tasks, execute=(a.command == "run" and a.execute))
        if a.command == "freeze":
            suite = json.load(open(SUITE))
            repo = _env()["GITHUB_REPOSITORY"]
            sha = gh(["api", f"repos/{repo.split('/')[0]}/{suite['app']}/commits/main", "--jq", ".sha"]).strip()
            suite["base_sha"] = sha
            SUITE.write_text(json.dumps(suite, indent=2) + "\n")
            print(f"froze {suite['app']} at {sha}")
            return 0
        result = json.load(open(a.path))
        if a.command == "compare":
            base = json.load(open(BASELINE))
            verdict = compare(result["aggregate"], base["aggregate"], json.load(open(RULES)))
            print(render_report(result["label"], result["candidate"], result["aggregate"], verdict))
            return 0 if verdict["accept"] else 1
        BASELINE.write_text(json.dumps({"label": result["label"], "candidate": result["candidate"], "aggregate": result["aggregate"]}, indent=2) + "\n")
        print(f"{BASELINE} now holds '{result['label']}'. Commit it.")
        return 0
    except (ValueError, RuntimeError, KeyError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
