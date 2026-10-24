#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import yaml
from request import intake_labels, render_form
from shared import api_check, config, github, http_client, outcomes, preview_token, shell

ROOT = config.FACTORY_DIR
SUITE = ROOT / "agents" / "benchmark" / "suite.json"
RULES = ROOT / "agents" / "benchmark" / "rules.json"
BASELINE = ROOT / "agents" / "benchmark" / "baseline.json"
ROLES = ("coder", "tester", "reviewer", "planner", "pipeline", "retrospective")
BENCH_LIMITS = {"flag_retirement": {"piggyback_max": 0}, "watchdog_minutes": 2, "daily_cost_cap_usd": 0}
DEFAULT_RULES = {"max_pass_drop": 1, "max_cost_ratio": 1.3, "max_rounds_delta": 0.5, "must_pass_tags": ["refusal", "safety"], "improvement_ratio": 0.9}


def parse_candidate(text):
    out = {}
    for pair in [p.strip() for p in (text or "").split(",") if p.strip()]:
        role, _, model = pair.partition("=")
        if role not in ROLES or not re.fullmatch(r"[\w./:-]+", model or ""):
            raise ValueError(f"bad candidate pair {pair!r}: use role=model-id with a role in {', '.join(ROLES)}")
        out[role] = model
    return out


def candidate_profile(profile_text, overrides):
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


def task_problems(tid, t, suite):
    problems = [] if t.get("request") else [f"{tid}: no request"]
    outcomes = (t.get("expected") or {}).get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        problems.append(f"{tid}: expected.outcomes is required")
    if not isinstance(t.get("oracle", {}).get("checks"), list):
        problems.append(f"{tid}: oracle.checks must be a list (empty for a task that must be refused)")
    if "{seed_flag}" in t.get("request", "") and suite.get("base_sha") and not suite.get("seed_flag"):
        problems.append(f"{tid}: the request names {{seed_flag}} but the suite has none: run `freeze --seed-flag issue-<n>`")
    ids = [c.get("id") for c in t.get("oracle", {}).get("checks", []) + t.get("setup", [])]
    return problems + ([f"{tid}: duplicate oracle or setup check ids"] if len(ids) != len(set(ids)) else [])


def validate_suite(suite):
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
        problems += task_problems(tid, t, suite)
    return problems


def fill_request(request, pass_id, seed_flag=""):
    return request.replace("{pass}", pass_id).replace("{seed_flag}", seed_flag)


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


PLANNING_STOP = re.compile(r"\*\*Planning stopped \(([a-z ]+)\)")


def planning_ending(comments, children):
    if children:
        return "planned"
    for body in reversed(comments or []):
        m = PLANNING_STOP.search(body or "")
        if m:
            return m.group(1).strip().replace(" ", "_")
    return None


def child_order(children):
    numbers = {c["number"] for c in children}
    waiting = {c["number"]: {b for b in c.get("blockers", []) if b in numbers} for c in children}
    out = []
    while waiting:
        ready = sorted(n for n, deps in waiting.items() if not deps - set(out))
        if not ready:
            raise ValueError("the plan's children block each other")
        out.append(ready[0])
        del waiting[ready[0]]
    return out


def ledger_cost(ledger_lines, run_id):
    for line in ledger_lines:
        m = re.search(rf"\b(\d+(?:\.\d+)?) run:{re.escape(str(run_id))}-plan\b", line)
        if m:
            return float(m.group(1))
    return 0.0


def planning_report(ending, cost, started=None, finished=None):
    return {"outcome": ending, "spent_usd": round(cost, 4), "review_passes": 0, "started_at": started, "finished_at": finished}


def merge_reports(plan_cost, reports):
    reports = [r for r in reports if r]
    if not reports:
        return None
    bad = next((r for r in reports if r.get("outcome") not in outcomes.OK), None)
    return {"outcome": (bad or reports[-1]).get("outcome"), "spent_usd": round(plan_cost + sum(float(r.get("spent_usd") or 0) for r in reports), 4),
            "review_passes": sum(int(r.get("review_passes") or 0) for r in reports), "started_at": reports[0].get("started_at"), "finished_at": reports[-1].get("finished_at")}


def newest_run_after(runs, before_id):
    newer = [r["databaseId"] for r in runs if r["databaseId"] > (before_id or 0)]
    return min(newer) if newer else None


def minutes_between(a, b):
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        return round((time.mktime(time.strptime(b[:19], fmt)) - time.mktime(time.strptime(a[:19], fmt))) / 60, 1)
    except (TypeError, ValueError):
        return None


def aggregate(scores):
    n = len(scores)
    ran = [s for s in scores if s["rounds"]]
    minutes = [s["minutes"] for s in scores if s["minutes"] is not None]
    return {"tasks": n, "passed": sum(s["passed"] for s in scores), "cost_usd": round(sum(s["cost_usd"] for s in scores), 4),
            "minutes": round(sum(minutes), 1), "rounds_mean": round(sum(s["rounds"] for s in ran) / len(ran), 2) if ran else 0.0,
            "failed": [s["id"] for s in scores if not s["passed"]], "by_task": {s["id"]: s for s in scores}}


def lost_tagged_passes(candidate, baseline, rules):
    reasons = []
    for tid, base in baseline.get("by_task", {}).items():
        now = candidate.get("by_task", {}).get(tid)
        if base.get("passed") and now is not None and not now.get("passed") and set(base.get("tags", [])) & set(rules["must_pass_tags"]):
            reasons.append(f"{tid} ({', '.join(base['tags'])}) passed in the baseline and failed now: {now.get('outcome')}")
    return reasons


def ratio(candidate_value, baseline_value):
    return candidate_value / baseline_value if baseline_value else 1.0


def regression_reasons(candidate, baseline, rules):
    reasons = []
    drop = baseline["passed"] - candidate["passed"]
    if drop > rules["max_pass_drop"]:
        reasons.append(f"passes {candidate['passed']} of {candidate['tasks']}, {drop} fewer than the baseline's {baseline['passed']} (allowed: {rules['max_pass_drop']})")
    reasons += lost_tagged_passes(candidate, baseline, rules)
    cost_ratio = ratio(candidate["cost_usd"], baseline["cost_usd"])
    if cost_ratio > rules["max_cost_ratio"]:
        reasons.append(f"cost ${candidate['cost_usd']:.2f} is {cost_ratio:.2f}x the baseline's ${baseline['cost_usd']:.2f} (allowed: {rules['max_cost_ratio']}x)")
    rounds_delta = candidate["rounds_mean"] - baseline["rounds_mean"]
    if rounds_delta > rules["max_rounds_delta"]:
        reasons.append(f"rounds per run rose by {rounds_delta:.2f} (allowed: {rules['max_rounds_delta']})")
    return reasons


def compare(candidate, baseline, rules=None):
    rules = {**DEFAULT_RULES, **(rules or {})}
    reasons = regression_reasons(candidate, baseline, rules)
    cost_ratio, minutes_ratio = ratio(candidate["cost_usd"], baseline["cost_usd"]), ratio(candidate["minutes"], baseline["minutes"])
    better = cost_ratio <= rules["improvement_ratio"] or minutes_ratio <= rules["improvement_ratio"]
    return {"accept": not reasons, "reasons": reasons, "improvement": bool(not reasons and better),
            "deltas": {"passed": candidate["passed"] - baseline["passed"], "cost_ratio": round(cost_ratio, 2), "minutes_ratio": round(minutes_ratio, 2),
                       "rounds_delta": round(candidate["rounds_mean"] - baseline["rounds_mean"], 2)}}


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
    ran = [t for t in tasks if "refusal" not in t.get("tags", [])]
    return {"runs": len(ran), "refusals": len(tasks) - len(ran), "cost_low": round(0.16 * len(ran), 2), "cost_high": round(0.7 * len(ran) + 0.1 * (len(tasks) - len(ran)), 2),
            "hours_low": round(0.35 * len(ran), 1), "hours_high": round(0.7 * len(ran), 1)}


def _env():
    return os.environ


def gh(args, token=None, check=True):
    p = shell.run_bounded(["gh", *args], None, {**os.environ, "GH_TOKEN": token or os.environ["FACTORY_PAT"]}, None)
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {(p.stderr or p.stdout)[-300:]}")
    return p.stdout


def publish_branch(repo, branch, profile_text):
    sha = gh(["api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"]).strip()
    gh(["api", "-X", "POST", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}"])
    file_sha = gh(["api", f"repos/{repo}/contents/agents/profiles.yml?ref={branch}", "--jq", ".sha"]).strip()
    gh(["api", "-X", "PUT", f"repos/{repo}/contents/agents/profiles.yml", "-f", f"message=Benchmark candidate profile for {branch}", "-f", f"branch={branch}",
        "-f", f"sha={file_sha}", "-f", "content=" + base64.b64encode(profile_text.encode()).decode()])


def delete_branch(repo, branch):
    gh(["api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{branch}"], check=False)


def reset_bench(owner, app, base_sha):
    header = "Authorization: Basic " + base64.b64encode(f"x-access-token:{os.environ['FACTORY_PAT']}".encode()).decode()
    env = {**os.environ, **github.git_auth_env(header)}
    work = tempfile.mkdtemp(prefix="bench-")
    url = f"https://github.com/{owner}/{app}.git"
    shell.sh(["git", "clone", "-q", "--no-checkout", url, work], env=env)
    head = shell.sh(["git", "rev-parse", "origin/main"], cwd=work).stdout.strip()
    if head == base_sha:
        return False
    shell.sh(["git", "push", "-q", "--force", "origin", f"{base_sha}:refs/heads/main"], cwd=work, env=env)
    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        runs = json.loads(gh(["run", "list", "--repo", f"{owner}/{app}", "--workflow", "deploy-fly.yml", "--limit", "10", "--json", "headSha,status,conclusion"], check=False) or "[]")
        mine = [r for r in runs if r["headSha"] == base_sha]
        if mine and all(r["status"] == "completed" for r in mine) and any(r["conclusion"] == "success" for r in mine):
            return True
        time.sleep(20)
    return True


def file_task_issue(repo, app, pass_id, task, seed_flag=""):

    token = os.environ["FACTORY_PAT"]
    for label in (intake_labels.UPDATE_APP_INTAKE, f"app:{app}", "benchmark"):
        github.ensure_label(repo, label, token, "ededed", "Benchmark pass")
    body = render_form.form_body(app, fill_request(task["request"], pass_id, seed_flag), f"{task.get('cost_cap', 1.0):.2f}")
    out = gh(["issue", "create", "--repo", repo, "--title", f"bench {pass_id}: {task['id']}", "--label", f"{intake_labels.UPDATE_APP_INTAKE},app:{app},benchmark", "--body", body])
    return re.search(r"/issues/(\d+)", out).group(1)


def dispatch_and_wait(repo, workflow, branch, inputs, timeout_min=75):
    def runs():
        return json.loads(gh(["run", "list", "--repo", repo, "--workflow", workflow, "--branch", branch, "--limit", "10", "--json", "databaseId,status,createdAt"], check=False) or "[]")
    before = max([r["databaseId"] for r in runs()] or [0])
    gh(["workflow", "run", workflow, "--repo", repo, "--ref", branch, *[a for k, v in inputs.items() for a in ("-f", f"{k}={v}")]])
    run_id, deadline = None, time.time() + timeout_min * 60
    while time.time() < deadline:
        found = runs()
        run_id = run_id or newest_run_after(found, before)
        mine = [r for r in found if r["databaseId"] == run_id]
        if mine and mine[0]["status"] == "completed":
            return run_id
        time.sleep(30)
    return run_id


def plan_children(repo, issue):
    out = json.loads(gh(["api", f"repos/{repo}/issues/{issue}/sub_issues?per_page=100"], check=False) or "[]")
    return [{"number": c["number"], "blockers": [b["number"] for b in json.loads(gh(["api", f"repos/{repo}/issues/{c['number']}/dependencies/blocked_by"], check=False) or "[]")]} for c in out]


def planning_cost(repo, run_id):
    ledger = json.loads(gh(["issue", "list", "--repo", repo, "--label", "factory-ledger", "--state", "open", "--json", "number"], check=False) or "[]")
    if not ledger or not run_id:
        return 0.0
    comments = json.loads(gh(["issue", "view", str(ledger[0]["number"]), "--repo", repo, "--json", "comments"], check=False) or "{}").get("comments", [])
    return ledger_cost([c.get("body", "") for c in comments], run_id)


def run_task(repo, app, branch, issue):
    plan_run = dispatch_and_wait(repo, "plan.yml", branch, {"issue_number": issue}, timeout_min=30)
    cost = planning_cost(repo, plan_run)
    children = plan_children(repo, issue)
    comments = [c.get("body", "") for c in json.loads(gh(["issue", "view", str(issue), "--repo", repo, "--json", "comments"], check=False) or "{}").get("comments", [])]
    ending = planning_ending(comments, children)
    if not children:
        return planning_report(ending, cost) if ending else None
    reports = []
    for number in child_order(children):
        run_id = dispatch_and_wait(repo, "build-run.yml", branch, {"issue_number": number, "app_name": app})
        report = read_report(repo, run_id) if run_id else None
        reports.append(report)
        if not report or report.get("outcome") not in outcomes.OK:
            break
    return merge_reports(cost, reports)


def read_report(repo, run_id):
    d = tempfile.mkdtemp(prefix="bench-report-")
    gh(["run", "download", str(run_id), "--repo", repo, "-n", "build-run", "-D", d], check=False)
    found = sorted(Path(d).rglob("state.json"))
    return json.load(open(found[0], encoding="utf-8")) if found else None


def run_oracle(app, task):

    checks = list(task.get("setup", [])) + list(task.get("oracle", {}).get("checks", []))
    if not checks:
        return []
    token = preview_token.for_app(os.environ["PREVIEW_MASTER_SECRET"], app)
    results = api_check.run_checks(checks, f"https://{app}.fly.dev", token)
    setup_ids = {c["id"] for c in task.get("setup", [])}
    return [r for r in results if r["id"] not in setup_ids or not r.get("ok")]


def archive_bench_flags(app, keep=("bench-seed",)):
    status, r = http_client.request("GET", f"{config.GROWTHBOOK_API}/features?limit=500", os.environ["GROWTHBOOK_ADMIN_PAT"])
    for f in (r.get("features") or []) if isinstance(r, dict) else []:
        fid = f.get("id", "")
        if fid.startswith(f"{app}.feature.") and fid.split(".feature.")[-1] not in keep and not f.get("archived"):
            http_client.request("POST", f"{config.GROWTHBOOK_API}/features/{fid}", os.environ["GROWTHBOOK_ADMIN_PAT"], {"archived": True})


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def print_plan(label, overrides, suite, tasks):
    est = estimate(tasks)
    print(f"Pass '{label}': {len(tasks)} task(s) on {suite['app']}: {', '.join(t['id'] for t in tasks)}")
    print(f"Candidate: {', '.join(f'{r}={m}' for r, m in overrides.items()) or 'current profile (baseline pass)'}")
    print(f"Estimate: ${est['cost_low']} to ${est['cost_high']}, {est['hours_low']} to {est['hours_high']} hours ({est['runs']} Build Runs, {est['refusals']} refusals).")


def run_one_task(repo, app, branch, pass_id, suite, task):
    reset_bench(repo.split("/")[0], app, suite["base_sha"])
    issue = file_task_issue(repo, app, pass_id, task, suite.get("seed_flag", ""))
    report = run_task(repo, app, branch, issue)
    oracle = run_oracle(app, task) if report and report.get("outcome") in outcomes.OK else []
    score = score_task(task, report, oracle)
    print(f"{task['id']}: {'PASS' if score['passed'] else 'FAIL'} ({score['outcome']}, ${score['cost_usd']:.3f}, {score['rounds']} rounds)", flush=True)
    return score


def score_tasks_on_branch(repo, branch, pass_id, suite, tasks):
    app = suite["app"]
    try:
        return [run_one_task(repo, app, branch, pass_id, suite, task) for task in tasks]
    finally:
        delete_branch(repo, branch)
        archive_bench_flags(app, keep=(suite.get("seed_flag") or "bench-seed",))
        reset_bench(repo.split("/")[0], app, suite["base_sha"])


def write_result(label, overrides, pass_id, agg):
    base = load_json(BASELINE) if BASELINE.exists() else None
    verdict = compare(agg, base["aggregate"], load_json(RULES)) if base else None
    out = {"label": label, "candidate": overrides, "pass_id": pass_id, "aggregate": agg, "verdict": verdict}
    Path(f"benchmark-result-{label}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    report_md = render_report(label, overrides, agg, verdict)
    Path(f"benchmark-result-{label}.md").write_text(report_md, encoding="utf-8")
    print(report_md)


def run_pass(label, overrides, task_names, execute):
    suite = load_json(SUITE)
    problems = validate_suite(suite)
    if problems:
        print("suite problems:\n- " + "\n- ".join(problems))
        return 2
    tasks = select_tasks(suite, task_names)
    print_plan(label, overrides, suite, tasks)
    if not execute:
        print("Dry run: nothing was started. Add --execute to spend it.")
        return 0
    if not suite.get("base_sha"):
        print("suite.json has no base_sha: stage and seed the bench app, then run `benchmark.py freeze` (docs/benchmark-protocol.md).")
        return 2
    repo = os.environ["GITHUB_REPOSITORY"]
    pass_id = time.strftime("%m%d%H%M", time.gmtime())
    branch = f"bench/{re.sub(r'[^a-z0-9-]', '-', label.lower())}-{pass_id}"
    publish_branch(repo, branch, candidate_profile((ROOT / "agents" / "profiles.yml").read_text(), overrides))
    write_result(label, overrides, pass_id, aggregate(score_tasks_on_branch(repo, branch, pass_id, suite, tasks)))
    return 0


def freeze(seed_flag):
    suite = load_json(SUITE)
    repo = _env()["GITHUB_REPOSITORY"]
    sha = gh(["api", f"repos/{repo.split('/')[0]}/{suite['app']}/commits/main", "--jq", ".sha"]).strip()
    suite["base_sha"] = sha
    if seed_flag:
        suite["seed_flag"] = seed_flag
    SUITE.write_text(json.dumps(suite, indent=2) + "\n")
    print(f"froze {suite['app']} at {sha}")
    return 0


def compare_with_baseline(result):
    verdict = compare(result["aggregate"], load_json(BASELINE)["aggregate"], load_json(RULES))
    print(render_report(result["label"], result["candidate"], result["aggregate"], verdict))
    return 0 if verdict["accept"] else 1


def accept_as_baseline(result):
    BASELINE.write_text(json.dumps({"label": result["label"], "candidate": result["candidate"], "aggregate": result["aggregate"]}, indent=2) + "\n")
    print(f"{BASELINE} now holds '{result['label']}'. Commit it.")
    return 0


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="benchmark.py")
    ap.add_argument("command", choices=["plan", "run", "compare", "accept", "freeze"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--candidate", default="")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--seed-flag", default="", help="freeze: the flag the bench app was seeded with (for example issue-142)")
    return ap.parse_args(argv[1:])


def dispatch(a):
    overrides = parse_candidate(a.candidate)
    if a.command in ("plan", "run"):
        return run_pass(a.label, overrides, a.tasks, execute=(a.command == "run" and a.execute))
    if a.command == "freeze":
        return freeze(a.seed_flag)
    result = load_json(a.path)
    return compare_with_baseline(result) if a.command == "compare" else accept_as_baseline(result)


def main(argv):
    a = parse_args(argv)
    try:
        return dispatch(a)
    except (ValueError, RuntimeError, KeyError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
