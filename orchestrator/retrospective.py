#!/usr/bin/env python3
"""After every Build Run, released or not: record what it taught, propose the fix as a PR, and report back on the issue that started it.

A run is a chance to improve the whole system, whether it released or stopped. The retrospective reads what the run found: why it
ended as it did, the minor findings it shipped with (they no longer cause rounds, so they would otherwise be lost), and the
`improvements` the reviewer and tester suggested for avoiding what they found. Runs as its own workflow step after
`build_run.py finalize`, on every run, and never fails the run:

1. Facts: a deterministic record of the run (outcome, per-round blocking findings and which recurred,
   time and cost per stage, the improvements suggested), written as an artifact.
2. Issue: one `factory-learning` issue in ai-factory per distinct failure (a fingerprint in the title
   collapses repeats into a comment on the existing issue).
3. Improvements: each one the reviewer or tester suggested becomes a suggestion issue in the Managed App's repo (target
   `managed_app`) or a `factory-learning` issue in ai-factory (target `factory`), deduplicated and capped per run. The Agents only
   suggest; the Orchestrator files.
4. Retrospective Agent: reads the facts, names a root-cause category, and edits the Factory checkout
   (prompts, Starter Template, orchestrator) with the smallest change that would have prevented it. It runs only when there is
   something new to look at.
5. Pull request: the Orchestrator, not the Agent, validates the changed paths, runs the unit tests,
   commits to a branch and opens a PR for a human to review. The Agent never holds a credential.
6. Report: a short summary of the retrospective is commented on the issue that started the run (the story), so the story keeps what
   the run found and what was filed.

A run that finishes can still teach the Factory, so `lessons_from` also records: a
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

Usage: retrospective.py   (env as for build_run.py finalize, plus DEEPINFRA_API_KEY and FACTORY_PAT)
"""
import filecmp
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import build_run as b
import fixrequest

LABEL = "factory-learning"
CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap", "spec_ambiguity", "model_limit", "infra", "unknown")
# Where the retrospective Agent may propose changes. Never workflows (they hold the secrets), the Starter
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
FIXTURE_RE = re.compile(r"^(agents/replay/cases\.json|agents/lint-fixtures/|agents/smoke-coder/tasks/|orchestrator/test_|templates/starter/.*(\.test\.|\.spec\.|/tests?/))")
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
            "commits": d.get("commits", []), "flags": d.get("flags") or [], "cap_usd": d.get("cap_usd"), "review_passes": d.get("review_passes") or 0,
            "audit": d.get("audit") or [], "rollback": d.get("rollback"), "plan": d.get("plan"), "intake_kind": d.get("intake_kind"), "final_blocking": [f.get("summary", "") for f in d.get("blocking", [])],
            "rounds": rounds, "recurring_findings": recurring, "stages": stages,
            "final_minor": [{k: f.get(k, "") for k in ("summary", "evidence", "file", "line")} for f in final_minor],
            "improvements": [i for i in d.get("improvements") or [] if isinstance(i, dict) and i.get("summary")],
            "dark_broken": b.is_dark_broken(d), "bugs": [x for x in d.get("bugs") or [] if isinstance(x, dict) and x.get("check")]}


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
    return bool(limits.get("fix_requests", True)) and d.get("outcome") not in b.OK_OUTCOMES and d.get("outcome") not in ("provider_blocked", "refused")


def records_stuck_issue(outcome):
    """Whether a run's ending gets the generic `Stuck run` lesson. A release the watchdog switched off is already a
    specific, severe lesson (`watchdog_disabled`); recording it twice made two issues and two analyses for one event."""
    return outcome not in b.OK_OUTCOMES and outcome not in ("watchdog_disabled", "provider_blocked", "refused")


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
              render_facts(facts) + "\n_A retrospective analysis and, if one is possible, a proposed fix PR follow._"], token).stdout
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
            "consider undoing that change with a new one.\n\n" + seen], token)
        return closed_n, "reopened"
    out = gh(["issue", "create", "--repo", repo, "--label", LABEL, "--title", lesson["title"], "--body", seen], token).stdout
    m = re.search(r"/issues/(\d+)", out)
    return (int(m.group(1)) if m else None), "new"


MAX_MINORS = 5  # per run, so one noisy review cannot flood the trackers
MAX_BUGS = 5


def minor_title(summary):
    return f"Minor finding [{hashlib.sha1(normalize(summary).encode()).hexdigest()[:8]}] {summary[:60]}"


def find_open_issue(repo, token, title, label=None):
    args = ["issue", "list", "--repo", repo, "--state", "open", "--search", f"{title[:80]} in:title", "--json", "number,title"]
    out = gh(args + (["--label", label] if label else []), token).stdout
    return next((i["number"] for i in json.loads(out or "[]") if i["title"] == title), None)


TITLE_NOISE = re.compile(r"\[[^\]]*\]|^\s*(improvement|suggestion|minor finding|lesson|bug)\b:?", re.I)
SIMILAR = 0.6  # share of the words two issue titles have in common for them to count as the same problem


def content_words(text):
    words = re.findall(r"[a-z0-9]+", TITLE_NOISE.sub(" ", str(text).lower()))
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if len(w) > 2 and w not in STOP_WORDS}  # "say" and "says" match


def similar_open_issue(repo, token, summary, label=None, threshold=SIMILAR):
    """The number of an open issue in `repo` that is about the same problem as `summary`, or None. Reworded titles still match (compared by
    their content words, ignoring the `[fingerprint]` and the Improvement/Suggestion prefix), so a repeat adds context to the issue that
    exists instead of opening a second one. Looks at the 100 most recent open issues."""
    wanted = content_words(str(summary)[:60])
    if not wanted:
        return None
    out = gh(["issue", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,title"]
             + (["--label", label] if label else []), token).stdout
    best, found = 0.0, None
    for issue in json.loads(out or "[]"):
        have = content_words(issue["title"])
        score = len(wanted & have) / len(wanted | have) if have else 0.0
        if score > best:
            best, found = score, issue["number"]
    return found if best >= threshold else None


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
        have = find_open_issue(app_repo, pat, "Suggestion: " + m["summary"][:70]) or similar_open_issue(app_repo, pat, m["summary"])
        if have:
            gh(["issue", "comment", str(have), "--repo", app_repo, "--body",
                f"More context, from the reviewer in `{facts['app']}`: {m['summary']}\n\nEvidence: {m['evidence']}\n{('Where: ' + where) if where else ''}\n{facts['run_url']}"], pat)
        else:
            gh(["issue", "create", "--repo", app_repo, "--title", "Suggestion: " + m["summary"][:70], "--body",
                detail + f"\nFound by the reviewer during the Build Run: {facts['run_url']}"], pat)
        number = find_open_issue(repo, token, title, LABEL) or similar_open_issue(repo, token, m["summary"], LABEL)
        if number:
            gh(["issue", "comment", str(number), "--repo", repo, "--body", f"Seen again in `{facts['app']}`: {facts['run_url']}\n\n{m['summary']}\n{m['evidence']}"], token)
        else:
            out = gh(["issue", "create", "--repo", repo, "--label", LABEL, "--title", title, "--body",
                      detail + f"\nFirst seen in `{facts['app']}`: {facts['run_url']}"], token).stdout
            found = re.search(r"/issues/(\d+)", out)
            number = int(found.group(1)) if found else None
        if number:
            recorded.append((number, already_proposed(repo, token, number)))
    return recorded


BUG_LABEL = "bug"


def bug_notes(facts):
    """The bugs the tester noted, as the text added to the story's own issue."""
    lines = ["## Bugs the tester saw", "", f"Run: {facts['run_url']}", ""]
    for x in facts["bugs"][:MAX_BUGS]:
        what = "behaviour that was live before this change stopped working" if x["kind"] == "regression" else f"a check of the new change failed (flag `{x['flag'] or 'none'}`)"
        lines += [f"- **{x['check']}** ({what})", f"  - Evidence: {x['evidence'] or 'none given'}"] + ([f"  - Repro: {x['repro']}"] if x.get("repro") else [])
    return "\n".join(lines) + "\n"


def note_bugs_on_story(repo, token, number, facts, carried):
    """The bugs belong to the Managed App's own story, so they go on the Update Intake that started the run, not into a new issue: the
    story gets the `bug` label and, unless the retry comment already carries them (`carried`), a comment listing them. The retry (the
    start label added again) is the fix request's job and is bounded by `fix_request_max_attempts`. Once per run."""
    if not facts.get("bugs"):
        return False
    gh(["label", "create", BUG_LABEL, "--repo", repo, "--color", "d73a4a", "--description", "Something is not working"], token)
    gh(["issue", "edit", str(number), "--repo", repo, "--add-label", BUG_LABEL], token)
    if carried:
        return True
    marker = f"<!-- bugs:{facts['run_url']} -->"
    if marker in (gh(["issue", "view", str(number), "--repo", repo, "--json", "comments"], token).stdout or ""):
        return False
    gh(["issue", "comment", str(number), "--repo", repo, "--body", bug_notes(facts) + marker], token)
    return True


def improvement_title(i):
    return f"Improvement [{hashlib.sha1((i['target'] + normalize(i['summary'])).encode()).hexdigest()[:8]}] {i['summary'][:60]}"


def record_improvements(repo, token, app_repo, pat, facts):
    """File what the reviewer and tester suggested. A `managed_app` improvement is a suggestion in the app's own repo (once, while one is
    open); a `factory` improvement is a `factory-learning` issue in ai-factory (a comment when it is already open). Capped per run.
    Returns ([(factory issue number, already proposed)], [{target, summary, url}]) for the Agent and for the report."""
    gh(["label", "create", LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    for_agent, filed = [], []
    for i in facts.get("improvements", [])[:MAX_MINORS]:
        detail = f"{i['summary']}\n\nEvidence: {i.get('evidence') or 'none given'}\n\nSuggested by the {i['source']} during the Build Run: {facts['run_url']}"
        if i["target"] == "managed_app":
            title = "Suggestion: " + i["summary"][:70]
            number = find_open_issue(app_repo, pat, title) or similar_open_issue(app_repo, pat, i["summary"])
            if number:
                gh(["issue", "comment", str(number), "--repo", app_repo, "--body",
                    f"More context, from the {i['source']} in `{facts['app']}`: {i['summary']}\n\nEvidence: {i.get('evidence') or 'none given'}\n{facts['run_url']}"], pat)
            else:
                out = gh(["issue", "create", "--repo", app_repo, "--title", title, "--body", detail], pat).stdout
                found = re.search(r"/issues/(\d+)", out)
                number = int(found.group(1)) if found else None
            filed.append({"target": "managed_app", "summary": i["summary"], "url": f"https://github.com/{app_repo}/issues/{number}" if number else ""})
            continue
        title = improvement_title(i)
        number = find_open_issue(repo, token, title, LABEL) or similar_open_issue(repo, token, i["summary"], LABEL)
        if number:
            gh(["issue", "comment", str(number), "--repo", repo, "--body",
                f"Suggested again in `{facts['app']}` by the {i['source']}: {i['summary']}\n\nEvidence: {i.get('evidence') or 'none given'}\n{facts['run_url']}"], token)
        else:
            out = gh(["issue", "create", "--repo", repo, "--label", LABEL, "--title", title, "--body", detail], token).stdout
            found = re.search(r"/issues/(\d+)", out)
            number = int(found.group(1)) if found else None
        if number:
            for_agent.append((number, already_proposed(repo, token, number)))
        filed.append({"target": "factory", "summary": i["summary"], "url": f"https://github.com/{repo}/issues/{number}" if number else ""})
    return for_agent, filed


def render_retrospective(facts, filed, lessons, result=None, bugs=()):
    """The short summary commented on the issue that started the run."""
    notes = []
    if facts.get("dark_broken"):
        notes.append("**Dark feature left behind**: its flag stays off and the next attempt fixes it forward behind the same flag.")
    if facts["outcome"] == "regression":
        notes.append("**Regression**: behaviour that was live before this change stopped working, so the live app was rolled back to the previous "
                     "version. The commits stay in `main`, behind a flag that is off, and are fixed forward.")
    for x in bugs:
        notes.append(f"Bug noted on this issue ({x['kind']}): {x['check']}")
    if facts["recurring_findings"]:
        notes.append("Findings that came back across rounds: " + "; ".join(facts["recurring_findings"][:3]))
    if facts["final_minor"]:
        notes.append(f"{len(facts['final_minor'])} minor finding(s) shipped open and became suggestions.")
    for x in filed:
        notes.append(f"Improvement for the {'app' if x['target'] == 'managed_app' else 'Factory'}: {x['summary']}" + (f" ({x['url']})" if x["url"] else ""))
    for x in lessons:
        notes.append(f"Lesson: {x['detail'][:160]}")
    if result and result.get("root_cause"):
        notes.append(f"Cause named ({result.get('category')}): {result['root_cause'][:200]}")
    if not notes:
        notes.append("Nothing to improve was found.")
    head = [f"## Retrospective: `{facts['outcome']}`", "", f"{facts['message'] or ''} ([run]({facts['run_url']}))", "",
            f"{facts['review_passes']} review pass(es), ${facts['spent_usd'] or 0:.2f} of a ${facts['cap_usd'] or 0:.2f} cap, "
            f"{len(facts['commits'])} commit(s) pushed.", ""]
    return "\n".join(head + [f"- {n}" for n in notes]) + "\n"


def post_retrospective(repo, token, number, run_id, body):
    """Comment the summary on the issue that started the run, once per run (a re-run of this step does not post it twice)."""
    marker = f"<!-- retrospective:{run_id} -->"
    seen = gh(["issue", "view", str(number), "--repo", repo, "--json", "comments"], token).stdout or ""
    if marker in seen:
        return False
    gh(["issue", "comment", str(number), "--repo", repo, "--body", body + "\n" + marker], token)
    return True


def mint_agent(cfg, parent_key):
    """(credential, budget): a single-model DeepInfra credential limited to `retrospective_cost_cap_usd`, so the Agent never
    holds the parent key and one analysis cannot spend more than the cap. (None, None) if one cannot be minted."""
    try:
        limits = cfg["limits"]
        budget = b.Budget(parent_key, float(limits.get("retrospective_cost_cap_usd", 0.5)), int(limits["jwt_ttl_seconds"]))
        return budget.mint(cfg["roles"]["retrospective"]["model"]), budget
    except Exception as e:  # noqa: BLE001 - never fail the run
        b.log(f"could not mint a scoped credential for the retrospective Agent: {type(e).__name__}")
        return None, None


def mint_agent_key(cfg, parent_key):
    return mint_agent(cfg, parent_key)[0]


def record_agent_spend(budget, key, repo, token, run_id):
    """Add what the Agent actually spent to the spend ledger, so the daily cap sees it (best effort, never fails the run)."""
    try:
        spent = budget.refresh(key)
        b.log(f"retrospective agent spent ${spent:.4f}")
        b.record_spend_in_ledger({"app": "retrospective", "spent_usd": spent}, repo, f"{run_id}-pm", token)  # own id: the ledger counts a run id once
    except Exception as e:  # noqa: BLE001
        b.log(f"could not record the retrospective Agent's spend: {type(e).__name__}")


MAX_FILE_BYTES = 1_000_000


def agent_user():
    return os.environ.get("AGENT_USER") or None


def share_with(path, user):
    """Make what the Orchestrator just created readable and writable by the Agent user too (a copy's permissions drop the ACL's reach)."""
    if user:
        b.sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{user}:rwX,u:{os.environ.get('USER', 'runner')}:rwX", str(path)], check=False)


def listing(root):
    """({relative path: file} for regular files, {relative path: target} for symlinks) of a tree, skipping `.git`."""
    files, links = {}, {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                links[rel] = os.readlink(full)
            elif name in filenames:
                files[rel] = full
    return files, links


def tree_changes(before, after):
    """What the Agent did to its copy of the tree: ({path: "A" | "M" | "D"} for regular files, [symlinks it added or changed]). Two
    plain trees are compared, never a git directory the Agent could have booby-trapped (a hook or config the Orchestrator would run)."""
    bf, bl = listing(before)
    af, al = listing(after)
    changes = {}
    for rel, full in af.items():
        if rel not in bf:
            changes[rel] = "A"
        elif not filecmp.cmp(bf[rel], full, shallow=False):
            changes[rel] = "M"
    for rel in bf:
        if rel not in af and rel not in al:
            changes[rel] = "D"
    return changes, sorted(rel for rel in al if bl.get(rel) != al[rel])


def apply_changes(before, after, changes):
    """Copy the Agent's changes into the Orchestrator's own checkout, only for paths the Agent may change and files of a sane size.
    Returns the paths applied. Nothing the Agent made outside those paths ever reaches the checkout git runs in."""
    applied = []
    for rel, kind in sorted(changes.items()):
        if not allowed_path(rel):
            continue
        dest = Path(before) / rel
        if kind == "D":
            dest.unlink(missing_ok=True)
        elif (Path(after) / rel).stat().st_size <= MAX_FILE_BYTES:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(after) / rel, dest)
        else:
            continue
        applied.append(rel)
    return applied


def scratch_root():
    """A fresh directory for one Agent run, inside the Agent user's area when isolation is on (the Orchestrator's own temp
    directories are closed to it)."""
    base = Path(os.environ.get("BUILD_RUN_DIR") or tempfile.gettempdir())
    root = base / f"retrospective-{os.getpid()}-{int(time.time())}"
    root.mkdir(parents=True)
    return root


def run_tests(factory, root, user):
    """The orchestrator's unit tests over the Factory tree as it will be proposed, run as the Agent user in a throwaway copy with no
    credential in its environment: the Agent may have edited test files, and a test is code. True when they pass."""
    verify = root / "verify"
    shutil.copytree(factory, verify, ignore=shutil.ignore_patterns(".git", "node_modules"), symlinks=True)
    share_with(verify, user)
    env = {k: os.environ[k] for k in ("PATH", "LANG", "CI") if k in os.environ}
    env.update({"HOME": str(root / "home"), "TMPDIR": str(root / "tmp"), "PYTHONDONTWRITEBYTECODE": "1"})
    for name in ("tmp", "home"):
        (root / name).mkdir(exist_ok=True)
    share_with(root, user)
    out = root / "tests.out"
    rc = b.run_watched([sys.executable, "-m", "unittest", "discover", "orchestrator"], verify, env, out, 900, 0, user=user,
                       pidfile=root / "pgid-tests.txt")
    return rc == 0


def run_agent(factory, cfg, key, facts_path, result_path, timeout_min):
    """Run the retrospective Agent in a copy of the Factory tree, as the unprivileged Agent user when isolation is on (the same
    account and self-check as the Build Run's Agents), with a scrubbed environment and a capped scoped key. Whatever it changes is
    carried back into `factory` by `apply_changes`, only for allowed paths; its answer is copied to `result_path`. Returns False when
    isolation is on but cannot be proven, in which case no Agent runs."""
    user = agent_user()
    if user:
        problems = b.run_isolation_probes(user)
        if problems:
            b.log("retrospective Agent not run, isolation is not effective: " + "; ".join(problems))
            return False
    root = scratch_root()
    try:
        work, io, home = root / "work", root / "io", root / "home"
        io.mkdir()
        home.mkdir()
        shutil.copytree(factory, work, ignore=shutil.ignore_patterns(".git", "node_modules"), symlinks=True)
        facts_copy, result_copy = io / "facts.json", io / "result.json"
        shutil.copyfile(facts_path, facts_copy)
        share_with(root, user)
        prompt = b.render(b.load_prompt(cfg["roles"]["retrospective"]["prompt"]), {
            "app_name": "-", "build_kind": "-", "facts_path": facts_copy, "result_path": result_copy,
            "categories": ", ".join(CATEGORIES)})
        env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR", "CI") if k in os.environ}
        env.update({"HOME": str(home), "LLM_MODEL": "openai/" + cfg["roles"]["retrospective"]["model"],
                    "LLM_BASE_URL": cfg["provider"]["base_url"], "LLM_API_KEY": key, "RUNTIME": "process"})
        rc = b.run_watched(["openhands", "--headless", "--override-with-envs", "-t", prompt], work, env, root / "openhands.out",
                           timeout_min * 60, 0, user=user, pidfile=root / "pgid-agent.txt")
        if rc == "timeout":
            b.log("retrospective agent timed out")
        if result_copy.is_file():
            shutil.copyfile(result_copy, result_path)
        changes, links = tree_changes(factory, work)
        if links:
            b.log("retrospective Agent's symlinks ignored: " + ", ".join(links))
        applied = apply_changes(factory, work, changes)
        b.log(f"retrospective Agent changed {len(changes)} file(s); {len(applied)} in allowed paths carried over")
        return True
    finally:
        shutil.rmtree(root, ignore_errors=True)


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
        b.log(f"retrospective proposal rejected: {bad}")
        gh(["issue", "comment", str(issue_no), "--repo", repo, "--body",
            f"The retrospective Agent's proposed change was discarded by the guardrails: {bad}. No PR was opened."], pat)
        for c in keep:  # leave the checkout clean for whatever runs next
            b.sh(["git", "checkout", "--", c], cwd=factory, check=False)
            b.sh(["git", "clean", "-fdq", "--", c], cwd=factory, check=False)
        return None
    if open_learning_prs(repo, pat) >= max_open:
        b.log(f"{max_open} learning PRs are already open; not opening another")
        return None
    root = scratch_root()
    try:
        passed = run_tests(factory, root, agent_user())
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if not passed:
        b.log("retrospective proposal breaks the orchestrator tests; not opening a PR")
        return None
    branch = f"learning/run-{run_id}"
    for cmd in (["git", "checkout", "-q", "-b", branch], ["git", "config", "user.name", "ai-factory-retrospective"],
                ["git", "config", "user.email", "retrospective@ai-factory.local"], ["git", "add", "--", *keep],
                ["git", "commit", "-qm", f"Retrospective fix: {result.get('change_summary', 'proposed change')[:70]}\n\nFor #{issue_no}."]):
        b.sh(cmd, cwd=factory)
    auth = "AUTHORIZATION: basic " + __import__("base64").b64encode(f"x-access-token:{pat}".encode()).decode()
    b.sh(["git", "push", "-q", "origin", branch], cwd=factory, env={**os.environ, **b.git_auth_env(auth)})
    numstat = b.sh(["git", "diff", "--numstat", "HEAD~1", "HEAD"], cwd=factory).stdout
    fixture = lesson_has_fixture(keep)
    reason = (result.get("no_fixture_reason") or "").strip()
    auto = auto_merge_eligible(numstat)
    body = (f"Proposed by the retrospective Agent for #{issue_no}.\n\n**Category**: {result.get('category')}\n\n"
            f"**Root cause**: {result.get('root_cause')}\n\n**Change**: {result.get('change_summary')}\n\n"
            f"**Regression fixture**: {'included' if fixture else ('the lint rule is itself the check' if auto else ('none: ' + reason if reason else 'NONE, and no reason given'))}\n\n"
            + ("**Auto-merge candidate**: an additive lint or formatter change. It merges itself once the PR checks pass.\n\n" if auto
               else "Review before merging: this edits shared prompts, the Starter Template, the orchestrator or the Standards.\n\n"))
    label = []
    if auto:  # the label must exist, and be on the PR from the start: the checks workflow reads it from the opened event
        gh(["label", "create", "auto-merge-candidate", "--repo", repo, "--color", "0e8a16", "--description", "Merges itself after the PR checks pass"], pat)
        label = ["--label", "auto-merge-candidate"]
    out = gh(["pr", "create", "--repo", repo, "--head", branch, "--base", "main", "--title",
              f"Retrospective fix for #{issue_no}", "--body", body, *label], pat).stdout.strip()
    return out or None


def propose(factory, cfg, repo, pat, token, parent_key, facts_path, result_path, targets, run_id):
    """Run the Agent once for these lesson issues, comment its analysis on each, and open the PR."""
    key, budget = mint_agent(cfg, parent_key)
    if not key:
        return None
    result_path.unlink(missing_ok=True)
    ran = run_agent(factory, cfg, key, facts_path, result_path, int(cfg["limits"].get("retrospective_timeout_minutes", 15)))
    record_agent_spend(budget, key, repo, token, run_id)
    if not ran:
        return None
    result = b.load_json(result_path) or {}
    if result.get("category") not in CATEGORIES:
        for n in targets:
            gh(["issue", "comment", str(n), "--repo", repo, "--body", "The retrospective Agent produced no usable analysis."], token)
        return None
    pr = open_pr(factory, repo, pat, targets[0], result, run_id, int(cfg["limits"].get("max_open_learning_prs", 3)))
    for n in targets:
        gh(["issue", "comment", str(n), "--repo", repo, "--body",
            f"**Retrospective** ({result['category']}): {result.get('root_cause', '')}\n\n"
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
    if not key or "retrospective" not in cfg.get("roles", {}):
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
    if d.get("outcome") == "refused":
        return 0  # a refusal is a correct answer to an impossible request, not a failure to learn from or retry
    facts = collect_facts(work, d)
    if d.get("outcome") == "provider_blocked":
        # Not a lesson and not a fix request: nothing the Factory can change helps, and the Agent could not run anyway.
        try:
            b.log(f"provider alert: {fixrequest.file_provider_alert(repo, token, facts)}")
        except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
            b.log(f"could not file the provider alert: {type(e).__name__}: {e}")
        return 0
    lessons = lessons_from(facts)
    facts["signals"] = [{"kind": x["kind"], "detail": x["detail"]} for x in lessons]
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    facts_path, result_path = work / "artifacts" / "retrospective-facts.json", work / "retrospective-result.json"
    facts_path.write_text(json.dumps(facts, indent=2))
    app_repo = f"{repo.split('/')[0]}/{d['app']}"
    stuck_issue = record_issue(repo, token, facts) if records_stuck_issue(d.get("outcome")) else None
    minors = record_minors(repo, token, app_repo, pat, facts)
    new_minors = [n for n, proposed in minors if not proposed]
    suggested, filed = record_improvements(repo, token, app_repo, pat, facts)
    new_improvements = [n for n, proposed in suggested if not proposed]
    recorded = [record_lesson(repo, token, x, facts) for x in lessons]
    # The Agent looks at a lesson that is new or came back after its fix, or has no PR proposed yet.
    new_lessons = [n for n, status in recorded if n and (status in ("new", "reopened") or not already_proposed(repo, token, n))]
    targets = list(dict.fromkeys(([stuck_issue] if stuck_issue else []) + new_minors + new_improvements + new_lessons))
    cfg, key = b.load_config(), os.environ.get("DEEPINFRA_API_KEY")
    result = None
    if targets and key and "retrospective" in cfg.get("roles", {}):
        result = propose(b.FACTORY_DIR, cfg, repo, pat, token, key, facts_path, result_path, targets, os.environ.get("GITHUB_RUN_ID", "0"))
    filed_request = None
    if wants_fix_request(d, cfg.get("limits", {})):
        try:
            filed_request = fixrequest.file_fix_request(repo, token, pat, facts, result, d.get("rollback"), cfg.get("limits", {}))
            b.log(f"fix request ({filed_request['target']}, {'started' if filed_request['started'] else 'not started'}): {filed_request['url']}")
        except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
            b.log(f"could not file the fix request: {type(e).__name__}: {e}")
    bugs = []
    if facts.get("bugs") and stuck:
        try:  # app-side bugs go on the story's own issue; a retry on that issue (above) already carries them in its comment
            carried = bool(filed_request and filed_request["target"] == "app")
            if note_bugs_on_story(repo, token, d["issue_number"], facts, carried):
                bugs = [{"kind": x["kind"], "check": x["check"], "url": ""} for x in facts["bugs"][:MAX_BUGS]]
        except Exception as e:  # noqa: BLE001
            b.log(f"could not note the bugs on the story: {type(e).__name__}: {e}")
    try:  # the story keeps what the run found, whether or not it released
        post_retrospective(repo, token, d["issue_number"], os.environ.get("GITHUB_RUN_ID", "0"),
                           render_retrospective(facts, filed, lessons, result, bugs))
    except Exception as e:  # noqa: BLE001
        b.log(f"could not post the retrospective on the issue: {type(e).__name__}: {e}")
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
    except Exception as e:  # noqa: BLE001 - the retrospective must never fail the run
        print(f"retrospective failed: {type(e).__name__}: {e}", flush=True)
        sys.exit(0)
