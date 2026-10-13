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

Beyond stuck runs, a run that finishes can still teach the Factory, so `lessons_from` also records: a
release the watchdog switched off, a run that needed many review rounds, a first test pass the coder had to
fix, a run that spent most of its budget, and a stage that ran very long. Each is a `factory-learning` issue
with a fingerprint. A lesson that was closed (its fix merged) and comes back is reopened as `fix-ineffective`,
so a change that did not work is visible. `lesson <issue>` (the Factory Run workflow) runs the same Agent and
PR path for an older lesson on demand.

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
import fixrequest

LABEL = "factory-learning"
CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap", "spec_ambiguity", "model_limit", "infra", "unknown")
# Where the post-mortem Agent may propose changes. Never workflows (they hold the secrets), the Starter
# Template's protected files, or anything outside the Factory's own prompts, template, orchestrator and docs.
ALLOWED_PREFIXES = ("agents/", "templates/starter/", "orchestrator/", "STANDARDS", "ARCHITECTURE.md", "GLOSSARY.md")
DENIED_PREFIXES = (".github/", "templates/starter/.github/", "templates/starter/fly/", "templates/starter/fly.toml")
MAX_LESSONS = 3  # signals recorded per run, so one noisy run cannot flood the tracker
EXTRA_ROUND_PASSES = 3  # review passes at or above which a clean run is still a lesson (two fix rounds)
BUDGET_SHARE = 0.7
SLOW_STAGE_SECONDS = 900
# Auto-merge is limited to additive changes to lint and formatter config in the Starter Template: they
# only add or tighten a deterministic check, and the Starter Template's own checks run on the PR first.
AUTO_MERGE_RE = re.compile(r"^templates/starter/(\.eslintrc[^/]*|eslint\.config\.[cm]?[jt]s|\.prettierrc[^/]*|"
                           r"prettier\.config\.[cm]?[jt]s|\.editorconfig)$")
# A lesson's change should come with something that would have caught it: a smoke or replay case, a test.
FIXTURE_RE = re.compile(r"^(agents/replay/cases\.json|agents/smoke-coder/tasks/|orchestrator/test_|templates/starter/.*(\.test\.|\.spec\.|/tests?/))")
SMOKE_DIFF_RE = re.compile(r"^agents/smoke/fixtures/[^/]+\.diff$")
SMOKE_EXPECTED = "agents/smoke/expected.json"
# Emphasis a prompt change must not add: a louder sentence is not a fix, and a model that was told so still adds it.
EMPHASIS_RE = re.compile(r"\b(CRITICAL|WARNING|ACTION REQUIRED|IMPORTANT|MUST NOT|MUST)\b|\u26a0|\*\*(CRITICAL|WARNING|IMPORTANT)")
APP_PATH_RE = re.compile(r"^diff --git a/(backend|frontend)/", re.M)
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
        entry = {"round": doc.get("round"), "blocking": [f.get("summary", "") for f in doc.get("blocking", [])],
                 "tester_blocking": [f.get("summary", "") for f in doc.get("blocking", []) if f.get("source") == "tester"]}
        rounds.append(entry)
        for s in entry["blocking"]:
            seen.setdefault(normalize(s), []).append(entry["round"])
    recurring = sorted(k for k, v in seen.items() if len(v) > 1)
    stages = [{"stage": s["stage"], "round": s["round"], "verdict": s["verdict"], "cost_usd": s["cost_usd"],
               "seconds": (s.get("usage") or {}).get("seconds"), "calls": (s.get("usage") or {}).get("calls")}
              for s in d.get("stages", [])]
    return {"app": d.get("app"), "outcome": d.get("outcome"), "message": d.get("message"),
            "run_url": d.get("run_url"), "issue_number": d.get("issue_number"), "spent_usd": d.get("spent_usd"),
            "commits": d.get("commits", []), "cap_usd": d.get("cap_usd"), "review_passes": d.get("review_passes") or 0,
            "audit": d.get("audit") or [], "revert": d.get("revert"), "plan": d.get("plan"), "intake_kind": d.get("intake_kind"), "final_blocking": [f.get("summary", "") for f in d.get("blocking", [])],
            "rounds": rounds, "recurring_findings": recurring, "stages": stages,
            "final_minor": [{k: f.get(k, "") for k in ("summary", "evidence", "file", "line")} for f in final_minor]}


def fingerprint(facts):
    """Stable across runs of the same failure: outcome plus the recurring (else final) findings."""
    basis = facts["recurring_findings"] or sorted(normalize(s) for s in facts["final_blocking"])
    return hashlib.sha1(json.dumps([facts["outcome"], basis]).encode()).hexdigest()[:8]


def lesson_fingerprint(kind, basis):
    return hashlib.sha1(json.dumps([kind, basis]).encode()).hexdigest()[:8]


def lessons_from(facts):
    """Things a run taught the Factory beyond being stuck. Each is {kind, title, severe, detail}; at most
    MAX_LESSONS, the severe ones first. A stuck run is recorded separately by record_issue."""
    outcome, ok = facts["outcome"], facts["outcome"] in b.OK_OUTCOMES
    found = []

    def add(kind, basis, detail, severe=False):
        found.append({"kind": kind, "severe": severe, "detail": detail,
                      "title": f"Lesson [{kind}] {lesson_fingerprint(kind, basis)}"})

    if facts.get("audit"):
        add("audit_violation", sorted(a["rule"] for a in facts["audit"]),
            "The run broke a design invariant: " + "; ".join(f"{a['rule']}: {a['detail']}" for a in facts["audit"]), severe=True)
    if outcome == "watchdog_disabled":
        add("watchdog_disabled", [], f"The watchdog switched a release off: {facts['message']}", severe=True)
    if ok and facts.get("review_passes", 0) >= EXTRA_ROUND_PASSES:
        basis = facts["recurring_findings"] or sorted({normalize(s) for r in facts["rounds"] for s in r["blocking"]})
        add("many_rounds", basis, f"It needed {facts['review_passes']} review passes. Blocking findings across the rounds: "
            + "; ".join(sorted({s for r in facts["rounds"] for s in r["blocking"]}) or ["none recorded"]))
    first_test = facts["rounds"][0]["tester_blocking"] if facts["rounds"] else []
    if ok and first_test:
        add("first_pass_test_failure", sorted(normalize(s) for s in first_test),
            "The first test pass failed and the coder had to fix: " + "; ".join(first_test))
    if ok and facts.get("cap_usd") and (facts.get("spent_usd") or 0) >= BUDGET_SHARE * facts["cap_usd"]:
        add("budget_high", [], f"It spent ${facts['spent_usd']:.2f} of its ${facts['cap_usd']:.2f} cap.")
    for st in facts["stages"]:
        if (st.get("seconds") or 0) > SLOW_STAGE_SECONDS:
            add("slow_stage", [st["stage"]], f"The {st['stage']} stage (round {st['round']}) took {st['seconds']:.0f}s.")
            break
    found.sort(key=lambda x: not x["severe"])
    return found[:MAX_LESSONS]


def pick_existing(issues, title):
    """(open issue number, closed issue number) among issues whose title matches exactly."""
    open_n = next((i["number"] for i in issues if i["title"] == title and i.get("state", "OPEN").upper() == "OPEN"), None)
    closed_n = next((i["number"] for i in issues if i["title"] == title and i.get("state", "").upper() == "CLOSED"), None)
    return open_n, closed_n


def added_lines(patch_text):
    """The lines a unified diff adds (not the `+++` file headers)."""
    return [l[1:] for l in patch_text.splitlines() if l.startswith("+") and not l.startswith("+++")]


def adds_emphasis(patch_text):
    """True if a diff of agents/prompts/*.md adds shouting (CRITICAL, WARNING, MUST, a warning sign...). Only the
    added lines count, so a prompt that already says MUST somewhere is not blamed for it."""
    return any(EMPHASIS_RE.search(l) for l in added_lines(patch_text))


def bad_fixture_reason(fixture_diffs):
    """Why new reviewer smoke fixtures cannot be used, or None. `fixture_diffs` maps each new
    agents/smoke/fixtures/*.diff path to its text. The reviewer is shown a Managed App's change, so a fixture that is
    not a diff of app code (for example a diff of a Factory prompt) tests nothing the reviewer ever sees."""
    for path, text in fixture_diffs.items():
        if not APP_PATH_RE.search(text):
            return f"{path} is not a diff of Managed App code (it must change files under backend/ or frontend/)"
    return None


def wants_fix_request(d, limits):
    """A fix request is filed for every Build Run that did not end well (`planned` and the good endings do not)."""
    return bool(limits.get("fix_requests", True)) and d.get("outcome") not in b.OK_OUTCOMES and d.get("outcome") != "provider_blocked"


def records_stuck_issue(outcome):
    """Whether a run's ending gets the generic `Stuck run` lesson. A release the watchdog switched off is already a
    specific, severe lesson (`watchdog_disabled`); recording it twice made two issues and two analyses for one event."""
    return outcome not in b.OK_OUTCOMES and outcome not in ("watchdog_disabled", "provider_blocked")


def lesson_has_fixture(paths):
    """True when a change set includes a test, smoke case or replay case alongside the fix."""
    # A reviewer smoke fixture only counts as a pair: the diff the reviewer is shown and its expected.json entry. The
    # harness runs every fixtures/*.diff, so stray files in that folder would exercise nothing.
    if any(SMOKE_DIFF_RE.match(p) for p in paths) and SMOKE_EXPECTED in paths:
        return True
    return any(FIXTURE_RE.match(p) for p in paths)


def auto_merge_eligible(numstat):
    """`git diff --numstat` lines -> True only if every changed file is lint/formatter config in the
    Starter Template and nothing was deleted (the change can only add or tighten a check)."""
    rows = [line.split("\t") for line in numstat.splitlines() if line.strip()]
    if not rows:
        return False
    for row in rows:
        if len(row) != 3:
            return False
        added, deleted, path = row
        if not AUTO_MERGE_RE.match(path) or deleted != "0" or added == "-":
            return False
    return True


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


def record_lesson(repo, token, lesson, facts):
    """Create or update the `factory-learning` issue for a lesson. Returns (number, status) with status
    `new`, `again` (an open one exists) or `reopened` (a closed one came back: the fix did not work)."""
    gh(["label", "create", LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    gh(["label", "create", "fix-ineffective", "--repo", repo, "--color", "b60205", "--description", "A lesson came back after its fix merged"], token)
    found = gh(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "all", "--search", f"{lesson['title']} in:title",
                "--json", "number,title,state"], token).stdout
    open_n, closed_n = pick_existing(json.loads(found or "[]"), lesson["title"])
    seen = f"{lesson['detail']}\n\nApp `{facts['app']}`, run: {facts['run_url']}"
    if open_n:
        gh(["issue", "comment", str(open_n), "--repo", repo, "--body", "Seen again.\n\n" + seen], token)
        return open_n, "again"
    if closed_n:
        gh(["issue", "reopen", str(closed_n), "--repo", repo], token)
        gh(["issue", "edit", str(closed_n), "--repo", repo, "--add-label", "fix-ineffective"], token)
        gh(["issue", "comment", str(closed_n), "--repo", repo, "--body",
            "**Fix ineffective:** this lesson was closed, and it happened again. The change that closed it did not stop it; "
            "consider reverting that change.\n\n" + seen], token)
        return closed_n, "reopened"
    out = gh(["issue", "create", "--repo", repo, "--label", LABEL, "--title", lesson["title"], "--body", seen], token).stdout
    m = re.search(r"/issues/(\d+)", out)
    return (int(m.group(1)) if m else None), "new"


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


def mint_agent(cfg, parent_key):
    """(credential, budget): a single-model DeepInfra credential limited to `postmortem_cost_cap_usd`, so the Agent never
    holds the parent key and one analysis cannot spend more than the cap. (None, None) if one cannot be minted."""
    try:
        limits = cfg["limits"]
        budget = b.Budget(parent_key, float(limits.get("postmortem_cost_cap_usd", 0.5)), int(limits["jwt_ttl_seconds"]))
        return budget.mint(cfg["roles"]["postmortem"]["model"]), budget
    except Exception as e:  # noqa: BLE001 - never fail the run
        b.log(f"could not mint a scoped credential for the post-mortem Agent: {type(e).__name__}")
        return None, None


def mint_agent_key(cfg, parent_key):
    return mint_agent(cfg, parent_key)[0]


def record_agent_spend(budget, key, repo, token, run_id):
    """Add what the Agent actually spent to the spend ledger, so the daily cap sees it (best effort, never fails the run)."""
    try:
        spent = budget.refresh(key)
        b.log(f"post-mortem agent spent ${spent:.4f}")
        b.record_spend_in_ledger({"app": "postmortem", "spent_usd": spent}, repo, f"{run_id}-pm", token)  # own id: the ledger counts a run id once
    except Exception as e:  # noqa: BLE001
        b.log(f"could not record the post-mortem Agent's spend: {type(e).__name__}")


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


def open_learning_prs(repo, token):
    out = gh(["pr", "list", "--repo", repo, "--state", "open", "--json", "headRefName"], token).stdout
    return sum(1 for p in json.loads(out or "[]") if p["headRefName"].startswith("learning/"))


def rejected_proposal(factory, paths):
    """The guardrails that look at what the Agent actually changed. Returns the reason to discard it, or None."""
    prompts = [p for p in paths if p.startswith("agents/prompts/") and p.endswith(".md")]
    if prompts:
        patch_text = b.sh(["git", "diff", "HEAD", "--", *prompts], cwd=factory).stdout
        if adds_emphasis(patch_text):
            return "it adds emphasis (CRITICAL, WARNING, MUST, a warning sign) to a prompt; if a rule was missed, the fix is a check or a different cause, not a louder sentence"
    fixtures = [p for p in paths if re.match(r"^agents/smoke/fixtures/[^/]+\.diff$", p)]
    texts = {p: (Path(factory) / p).read_text() for p in fixtures if (Path(factory) / p).exists()}
    return bad_fixture_reason(texts)


def open_pr(factory, repo, pat, issue_no, result, run_id, max_open=3):
    """Validate what the Agent changed, test it, and open a PR. Returns the PR URL or None.
    The PR is labelled `auto-merge-candidate` only for an additive lint/formatter change; the PR checks
    workflow recomputes that and merges after its checks pass. Everything else waits for a human."""
    changed = [l[3:].strip() for l in b.sh(["git", "status", "--porcelain"], cwd=factory).stdout.splitlines() if l]
    bad = [c for c in changed if not allowed_path(c)]
    for c in bad:  # drop anything outside the allowed paths rather than refusing the whole proposal
        b.sh(["git", "checkout", "--", c], cwd=factory, check=False)
        b.sh(["git", "clean", "-fdq", "--", c], cwd=factory, check=False)
    keep = [c for c in changed if c not in bad]
    if not keep:
        return None
    bad = rejected_proposal(factory, keep)
    if bad:
        b.log(f"post-mortem proposal rejected: {bad}")
        gh(["issue", "comment", str(issue_no), "--repo", repo, "--body",
            f"The post-mortem Agent's proposed change was discarded by the guardrails: {bad}. No PR was opened."], pat)
        for c in keep:  # leave the checkout clean for whatever runs next
            b.sh(["git", "checkout", "--", c], cwd=factory, check=False)
            b.sh(["git", "clean", "-fdq", "--", c], cwd=factory, check=False)
        return None
    if open_learning_prs(repo, pat) >= max_open:
        b.log(f"{max_open} learning PRs are already open; not opening another")
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
    numstat = b.sh(["git", "diff", "--numstat", "HEAD~1", "HEAD"], cwd=factory).stdout
    fixture = lesson_has_fixture(keep)
    reason = (result.get("no_fixture_reason") or "").strip()
    auto = auto_merge_eligible(numstat)
    body = (f"Proposed by the post-mortem Agent for #{issue_no}.\n\n**Category**: {result.get('category')}\n\n"
            f"**Root cause**: {result.get('root_cause')}\n\n**Change**: {result.get('change_summary')}\n\n"
            f"**Regression fixture**: {'included' if fixture else ('the lint rule is itself the check' if auto else ('none: ' + reason if reason else 'NONE, and no reason given'))}\n\n"
            + ("**Auto-merge candidate**: an additive lint or formatter change. It merges itself once the PR checks pass.\n\n" if auto
               else "Review before merging: this edits shared prompts, the Starter Template, the orchestrator or the Standards.\n\n"))
    label = []
    if auto:  # the label must exist, and be on the PR from the start: the checks workflow reads it from the opened event
        gh(["label", "create", "auto-merge-candidate", "--repo", repo, "--color", "0e8a16", "--description", "Merges itself after the PR checks pass"], pat)
        label = ["--label", "auto-merge-candidate"]
    out = gh(["pr", "create", "--repo", repo, "--head", branch, "--base", "main", "--title",
              f"Post-mortem fix for #{issue_no}", "--body", body, *label], pat).stdout.strip()
    return out or None


def propose(factory, cfg, repo, pat, token, parent_key, facts_path, result_path, targets, run_id):
    """Run the Agent once for these lesson issues, comment its analysis on each, and open the PR."""
    key, budget = mint_agent(cfg, parent_key)
    if not key:
        return None
    result_path.unlink(missing_ok=True)
    run_agent(factory, cfg, key, facts_path, result_path, int(cfg["limits"].get("postmortem_timeout_minutes", 15)))
    record_agent_spend(budget, key, repo, token, run_id)
    result = b.load_json(result_path) or {}
    if result.get("category") not in CATEGORIES:
        for n in targets:
            gh(["issue", "comment", str(n), "--repo", repo, "--body", "The post-mortem Agent produced no usable analysis."], token)
        return None
    pr = open_pr(factory, repo, pat, targets[0], result, run_id, int(cfg["limits"].get("max_open_learning_prs", 3)))
    for n in targets:
        gh(["issue", "comment", str(n), "--repo", repo, "--body",
            f"**Post-mortem** ({result['category']}): {result.get('root_cause', '')}\n\n"
            f"**Proposed change**: {result.get('change_summary', 'none')}\n\n"
            + (f"**PR**: {pr}" if pr else "No change was proposed, it did not pass validation, or too many learning PRs are open.")], token)
    return result


def lesson_main(number):
    """The Factory Run: analyse one existing lesson issue (label `ready-for-factory-run`) on demand."""
    repo = os.environ["GITHUB_REPOSITORY"]
    pat, token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    issue = json.loads(gh(["issue", "view", str(number), "--repo", repo, "--json", "title,body,comments,labels"], token).stdout)
    if not {LABEL, fixrequest.FACTORY_LABEL} & {l["name"] for l in issue.get("labels", [])}:
        b.log(f"#{number} is not a {LABEL} or {fixrequest.FACTORY_LABEL} issue; nothing to do")
        return 0
    work = Path(tempfile.mkdtemp(prefix="factory-run-"))
    facts_path, result_path = work / "lesson.json", work / "result.json"
    facts_path.write_text(json.dumps({"lesson_issue": number, "title": issue["title"], "body": issue["body"],
                                      "comments": [c["body"] for c in issue.get("comments", [])][-10:]}, indent=2))
    cfg, key = b.load_config(), os.environ.get("DEEPINFRA_API_KEY")
    if not key or "postmortem" not in cfg.get("roles", {}):
        return 0
    propose(b.FACTORY_DIR, cfg, repo, pat, token, key, facts_path, result_path, [number], os.environ.get("GITHUB_RUN_ID", "0"))
    return 0


def main():
    work = Path(os.environ["BUILD_RUN_DIR"])
    d = b.load_json(work / "state.json")
    if not d:
        return 0
    stuck = d.get("outcome") not in b.OK_OUTCOMES
    repo = os.environ["GITHUB_REPOSITORY"]
    pat, token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    facts = collect_facts(work, d)
    if d.get("outcome") == "provider_blocked":
        # Not a lesson and not a fix request: nothing the Factory can change helps, and the Agent could not run anyway.
        try:
            b.log(f"provider alert: {fixrequest.file_provider_alert(repo, token, facts)}")
        except Exception as e:  # noqa: BLE001 - the post-mortem never fails the run
            b.log(f"could not file the provider alert: {type(e).__name__}: {e}")
        return 0
    lessons = lessons_from(facts)
    facts["signals"] = [{"kind": x["kind"], "detail": x["detail"]} for x in lessons]
    if not stuck and not facts["final_minor"] and not lessons:
        return 0
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    facts_path, result_path = work / "artifacts" / "postmortem-facts.json", work / "postmortem-result.json"
    facts_path.write_text(json.dumps(facts, indent=2))
    stuck_issue = record_issue(repo, token, facts) if records_stuck_issue(d.get("outcome")) else None
    minors = record_minors(repo, token, f"{repo.split('/')[0]}/{d['app']}", pat, facts)
    new_minors = [n for n, proposed in minors if not proposed]
    recorded = [record_lesson(repo, token, x, facts) for x in lessons]
    # The Agent looks at a lesson that is new or came back after its fix, or has no PR proposed yet.
    new_lessons = [n for n, status in recorded if n and (status in ("new", "reopened") or not already_proposed(repo, token, n))]
    targets = ([stuck_issue] if stuck_issue else []) + new_minors + new_lessons
    cfg, key = b.load_config(), os.environ.get("DEEPINFRA_API_KEY")
    result = None
    if targets and key and "postmortem" in cfg.get("roles", {}):
        result = propose(b.FACTORY_DIR, cfg, repo, pat, token, key, facts_path, result_path, targets, os.environ.get("GITHUB_RUN_ID", "0"))
    if wants_fix_request(d, cfg.get("limits", {})):
        try:
            filed = fixrequest.file_fix_request(repo, token, pat, facts, result, d.get("revert"), cfg.get("limits", {}))
            b.log(f"fix request ({filed['target']}, {'started' if filed['started'] else 'not started'}): {filed['url']}")
        except Exception as e:  # noqa: BLE001 - the post-mortem never fails the run
            b.log(f"could not file the fix request: {type(e).__name__}: {e}")
    return 0


def auto_merge_check(base, head):
    """Exit 0 only if the diff base...head is an additive lint/formatter change. The PR checks workflow
    calls this before merging a PR labelled `auto-merge-candidate`; it does not trust the label."""
    numstat = b.sh(["git", "diff", "--numstat", f"{base}...{head}"], cwd=b.FACTORY_DIR).stdout
    ok = auto_merge_eligible(numstat)
    print("auto-merge eligible" if ok else "not eligible for auto-merge (a human merges this)")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        if len(sys.argv) > 2 and sys.argv[1] == "lesson":
            sys.exit(lesson_main(int(sys.argv[2])))
        if len(sys.argv) > 3 and sys.argv[1] == "auto-merge-check":
            try:
                sys.exit(auto_merge_check(sys.argv[2], sys.argv[3]))
            except Exception as e:  # noqa: BLE001 - any doubt means a human merges it
                print(f"auto-merge check failed ({type(e).__name__}); a human merges this", flush=True)
                sys.exit(1)
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - the post-mortem must never fail the run
        print(f"post-mortem failed: {type(e).__name__}: {e}", flush=True)
        sys.exit(0)
