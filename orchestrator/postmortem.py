#!/usr/bin/env python3
"""After a Build Run that did not end clean: record why in the Factory, and propose the fix as a PR.

A stuck run is a chance to improve the whole system, not only to alert someone, and so are the minor
findings a run ships with (they no longer cause rounds, so they would otherwise be lost). Runs as its own
workflow step after `build_run.py finalize`, and never fails the run:

1. Facts: a deterministic record of the run (outcome, per-round blocking findings and which recurred,
   time and cost per stage), written as an artifact.
2. Issue: one `factory-learning` issue in ai-factory per distinct failure (a fingerprint in the title
   collapses repeats into a comment on the existing issue).
3. Post-mortem Agent: reads the facts, names a root-cause category, and edits the Factory checkout
   (prompts, Starter Template, orchestrator) with the smallest change that would have prevented it.
4. Pull request: the Orchestrator, not the Agent, validates the changed paths, runs the unit tests,
   commits to a branch and opens a PR for a human to review. The Agent never holds a credential.

Minor findings still open at the end of a run (clean or not) also become: a suggestion issue in the
Managed App's own repo (its backlog), and a `factory-learning` issue in ai-factory per distinct finding,
which the Agent considers for a generalizing prompt or template change straight away (no threshold:
the Agent must justify that it generalizes or decline, and a human reviews the PR). A finding whose
issue already records a proposed PR is not sent to the Agent again.

Usage: postmortem.py   (env as for build_run.py finalize, plus DEEPINFRA_API_KEY and FACTORY_PAT)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import build_run as b

LABEL = "factory-learning"
CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "spec_ambiguity", "model_limit", "infra", "unknown")
# Where the post-mortem Agent may propose changes. Never workflows (they hold the secrets), the Starter
# Template's protected files, or anything outside the Factory's own prompts, template, orchestrator and docs.
ALLOWED_PREFIXES = ("agents/", "templates/starter/", "orchestrator/", "STANDARDS", "ARCHITECTURE.md", "GLOSSARY.md")
DENIED_PREFIXES = (".github/", "templates/starter/.github/", "templates/starter/fly/", "templates/starter/fly.toml")
STOP_WORDS = {"the", "a", "an", "is", "are", "was", "to", "of", "in", "on", "for", "and", "not", "no", "it", "this"}


def allowed_path(path):
    return path.startswith(ALLOWED_PREFIXES) and not path.startswith(DENIED_PREFIXES) and ".." not in Path(path).parts


def normalize(summary):
    """The first few meaningful words of a finding, so rewordings of one problem match."""
    words = [w for w in re.findall(r"[a-z0-9]+", summary.lower()) if w not in STOP_WORDS]
    return " ".join(words[:6])


def collect_facts(work, d):
    """Deterministic facts about a run. `work` holds findings-N.json written per round."""
    rounds, seen, final_minor = [], {}, []
    for path in sorted(Path(work).glob("findings-*.json"), key=lambda p: p.name):
        doc = b.load_json(path) or {}
        if not doc.get("blocking") and not doc.get("round") and not doc.get("minor"):
            continue
        final_minor = doc.get("minor") or []
        entry = {"round": doc.get("round"), "blocking": [f.get("summary", "") for f in doc.get("blocking", [])]}
        rounds.append(entry)
        for s in entry["blocking"]:
            seen.setdefault(normalize(s), []).append(entry["round"])
    recurring = sorted(k for k, v in seen.items() if len(v) > 1)
    stages = [{"stage": s["stage"], "round": s["round"], "verdict": s["verdict"], "cost_usd": s["cost_usd"],
               "seconds": (s.get("usage") or {}).get("seconds"), "calls": (s.get("usage") or {}).get("calls")}
              for s in d.get("stages", [])]
    return {"app": d.get("app"), "outcome": d.get("outcome"), "message": d.get("message"),
            "run_url": d.get("run_url"), "issue_number": d.get("issue_number"), "spent_usd": d.get("spent_usd"),
            "commits": d.get("commits", []), "final_blocking": [f.get("summary", "") for f in d.get("blocking", [])],
            "rounds": rounds, "recurring_findings": recurring, "stages": stages,
            "final_minor": [{k: f.get(k, "") for k in ("summary", "evidence", "file", "line")} for f in final_minor]}


def fingerprint(facts):
    """Stable across runs of the same failure: outcome plus the recurring (else final) findings."""
    basis = facts["recurring_findings"] or sorted(normalize(s) for s in facts["final_blocking"])
    return hashlib.sha1(json.dumps([facts["outcome"], basis]).encode()).hexdigest()[:8]


def render_facts(facts):
    lines = [f"**App**: {facts['app']}  ", f"**Outcome**: `{facts['outcome']}`: {facts['message']}  ",
             f"**Run**: {facts['run_url']}  ", f"**Intake**: ai-factory#{facts['issue_number']}  ",
             f"**Spent**: ${facts['spent_usd'] or 0:.4f}", ""]
    for r in facts["rounds"]:
        lines += [f"Round {r['round']} blocking:"] + [f"- {s}" for s in r["blocking"]] + [""]
    if facts["recurring_findings"]:
        lines += ["Recurred across rounds (the coder did not resolve these):"] + [f"- {s}" for s in facts["recurring_findings"]] + [""]
    if facts["final_minor"]:
        lines += ["Minor findings still open at the end:"] + [f"- {m['summary']}" for m in facts["final_minor"]] + [""]
    lines += ["| Stage | Round | Verdict | Cost | Seconds | Calls |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['stage']} | {s['round']} | {s['verdict']} | ${s['cost_usd']:.4f} | {s['seconds'] or '-'} | {s['calls'] or '-'} |"
              for s in facts["stages"]]
    return "\n".join(lines) + "\n"


def title_for(facts):
    return f"Stuck run [{facts['outcome']}] {fingerprint(facts)}"


def gh(args, token, check=False):
    return b.sh(["gh", *args], env={**os.environ, "GH_TOKEN": token}, check=check)


def record_issue(repo, token, facts):
    """Create the learning issue, or comment on the open one for the same fingerprint. Returns its number."""
    gh(["label", "create", LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    title = title_for(facts)
    found = gh(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--search", f"{fingerprint(facts)} in:title",
                "--json", "number,title"], token).stdout
    for issue in json.loads(found or "[]"):
        if issue["title"] == title:
            gh(["issue", "comment", str(issue["number"]), "--repo", repo, "--body", "Happened again.\n\n" + render_facts(facts)], token)
            return issue["number"]
    out = gh(["issue", "create", "--repo", repo, "--label", LABEL, "--title", title, "--body",
              render_facts(facts) + "\n_A post-mortem analysis and, if one is possible, a proposed fix PR follow._"], token).stdout
    m = re.search(r"/issues/(\d+)", out)
    return int(m.group(1)) if m else None


MAX_MINORS = 5  # per run, so one noisy review cannot flood the trackers


def minor_title(summary):
    return f"Minor finding [{hashlib.sha1(normalize(summary).encode()).hexdigest()[:8]}] {summary[:60]}"


def find_open_issue(repo, token, title, label=None):
    args = ["issue", "list", "--repo", repo, "--state", "open", "--search", f"{title[:80]} in:title", "--json", "number,title"]
    out = gh(args + (["--label", label] if label else []), token).stdout
    return next((i["number"] for i in json.loads(out or "[]") if i["title"] == title), None)


def already_proposed(repo, token, number):
    out = gh(["issue", "view", str(number), "--repo", repo, "--json", "comments"], token).stdout
    return "**PR**: http" in out


def record_minors(repo, token, app_repo, pat, facts):
    """Suggestion issues in the Managed App's repo; one factory-learning issue per distinct finding.
    Returns [(factory issue number, already proposed)]."""
    gh(["label", "create", LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    recorded = []
    for m in facts["final_minor"][:MAX_MINORS]:
        title = minor_title(m["summary"])
        where = f"{m['file']}:{m['line']}" if m.get("file") else ""
        detail = f"{m['summary']}\n\nEvidence: {m['evidence']}\n{('Where: ' + where) if where else ''}\n"
        if not find_open_issue(app_repo, pat, "Suggestion: " + m["summary"][:70]):
            gh(["issue", "create", "--repo", app_repo, "--title", "Suggestion: " + m["summary"][:70], "--body",
                detail + f"\nFound by the reviewer during the Build Run: {facts['run_url']}"], pat)
        number = find_open_issue(repo, token, title, LABEL)
        if number:
            gh(["issue", "comment", str(number), "--repo", repo, "--body", f"Seen again in `{facts['app']}`: {facts['run_url']}"], token)
        else:
            out = gh(["issue", "create", "--repo", repo, "--label", LABEL, "--title", title, "--body",
                      detail + f"\nFirst seen in `{facts['app']}`: {facts['run_url']}"], token).stdout
            found = re.search(r"/issues/(\d+)", out)
            number = int(found.group(1)) if found else None
        if number:
            recorded.append((number, already_proposed(repo, token, number)))
    return recorded


def run_agent(factory, cfg, key, facts_path, result_path, timeout_min):
    prompt = b.render(b.load_prompt(cfg["roles"]["postmortem"]["prompt"]), {
        "app_name": "-", "build_kind": "-", "facts_path": facts_path, "result_path": result_path,
        "categories": ", ".join(CATEGORIES)})
    home = Path(tempfile.mkdtemp(prefix="postmortem-home-"))
    env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR", "CI") if k in os.environ}
    env.update({"HOME": str(home), "LLM_MODEL": "openai/" + cfg["roles"]["postmortem"]["model"],
                "LLM_BASE_URL": cfg["provider"]["base_url"], "LLM_API_KEY": key, "RUNTIME": "process"})
    try:
        subprocess.run(["openhands", "--headless", "--override-with-envs", "-t", prompt], cwd=factory, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_min * 60)
    except subprocess.TimeoutExpired:
        b.log("post-mortem agent timed out")


def open_pr(factory, repo, pat, issue_no, result, run_id):
    """Validate what the Agent changed, test it, and open a PR. Returns the PR URL or None."""
    changed = [l[3:].strip() for l in b.sh(["git", "status", "--porcelain"], cwd=factory).stdout.splitlines() if l]
    bad = [c for c in changed if not allowed_path(c)]
    for c in bad:  # drop anything outside the allowed paths rather than refusing the whole proposal
        b.sh(["git", "checkout", "--", c], cwd=factory, check=False)
        b.sh(["git", "clean", "-fdq", "--", c], cwd=factory, check=False)
    keep = [c for c in changed if c not in bad]
    if not keep:
        return None
    if b.sh([sys.executable, "-m", "unittest", "discover", "orchestrator"], cwd=factory, check=False).returncode != 0:
        b.log("post-mortem proposal breaks the orchestrator tests; not opening a PR")
        return None
    branch = f"learning/run-{run_id}"
    for cmd in (["git", "checkout", "-q", "-b", branch], ["git", "config", "user.name", "ai-factory-postmortem"],
                ["git", "config", "user.email", "postmortem@ai-factory.local"], ["git", "add", "--", *keep],
                ["git", "commit", "-qm", f"Post-mortem fix: {result.get('change_summary', 'proposed change')[:70]}\n\nFor #{issue_no}."]):
        b.sh(cmd, cwd=factory)
    auth = "AUTHORIZATION: basic " + __import__("base64").b64encode(f"x-access-token:{pat}".encode()).decode()
    b.sh(["git", "-c", f"http.extraheader={auth}", "push", "-q", "origin", branch], cwd=factory)
    body = (f"Proposed by the post-mortem Agent for #{issue_no}.\n\n**Category**: {result.get('category')}\n\n"
            f"**Root cause**: {result.get('root_cause')}\n\n**Change**: {result.get('change_summary')}\n\n"
            "Review before merging: this edits shared prompts, the Starter Template or the orchestrator.")
    out = gh(["pr", "create", "--repo", repo, "--head", branch, "--base", "main", "--title",
              f"Post-mortem fix for #{issue_no}", "--body", body], pat).stdout
    return out.strip() or None


def main():
    work = Path(os.environ["BUILD_RUN_DIR"])
    d = b.load_json(work / "state.json")
    if not d:
        return 0
    stuck = d.get("outcome") not in ("released", "nothing_to_release")
    repo = os.environ["GITHUB_REPOSITORY"]
    pat, token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    facts = collect_facts(work, d)
    if not stuck and not facts["final_minor"]:
        return 0
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    facts_path, result_path = work / "artifacts" / "postmortem-facts.json", work / "postmortem-result.json"
    facts_path.write_text(json.dumps(facts, indent=2))
    stuck_issue = record_issue(repo, token, facts) if stuck else None
    minors = record_minors(repo, token, f"{repo.split('/')[0]}/{d['app']}", pat, facts)
    new_minors = [n for n, proposed in minors if not proposed]
    targets = ([stuck_issue] if stuck_issue else []) + new_minors
    cfg, key = b.load_config(), os.environ.get("DEEPINFRA_API_KEY")
    if not targets or not key or "postmortem" not in cfg.get("roles", {}):
        return 0
    factory = b.FACTORY_DIR
    result_path.unlink(missing_ok=True)
    run_agent(factory, cfg, key, facts_path, result_path, int(cfg["limits"].get("postmortem_timeout_minutes", 15)))
    result = b.load_json(result_path) or {}
    if result.get("category") not in CATEGORIES:
        for n in targets:
            gh(["issue", "comment", str(n), "--repo", repo, "--body", "The post-mortem Agent produced no usable analysis."], token)
        return 0
    pr = open_pr(factory, repo, pat, targets[0], result, os.environ.get("GITHUB_RUN_ID", "0"))
    for n in targets:
        gh(["issue", "comment", str(n), "--repo", repo, "--body",
            f"**Post-mortem** ({result['category']}): {result.get('root_cause', '')}\n\n"
            f"**Proposed change**: {result.get('change_summary', 'none')}\n\n"
            + (f"**PR**: {pr}" if pr else "No change was proposed or it did not pass validation.")], token)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - the post-mortem must never fail the run
        print(f"post-mortem failed: {type(e).__name__}: {e}", flush=True)
        sys.exit(0)
