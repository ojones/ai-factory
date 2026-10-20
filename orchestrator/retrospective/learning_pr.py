# Step 5: the Orchestrator, not the Agent, validates the changed paths, runs the unit tests, commits to a branch and opens a PR for a human to review.
import json
import os
import re
import shutil
from pathlib import Path

from shared import agent_output, config, github
from shared.console import log
from shared.shell import sh

from retrospective import agent_run, tracker

# Auto-merge is limited to additive changes to lint and formatter config in the Starter Template: they
# only add or tighten a deterministic check, and the Starter Template's own checks run on the PR first.
AUTO_MERGE_RE = re.compile(r"^templates/starter/(\.eslintrc[^/]*|eslint\.config\.[cm]?[jt]s|\.prettierrc[^/]*|"
                           r"prettier\.config\.[cm]?[jt]s|\.editorconfig)$")


# A lesson's change should come with something that would have caught it: a smoke or replay case, a test.
FIXTURE_RE = re.compile(r"^(agents/replay/cases\.json|agents/lint-fixtures/|agents/smoke-coder/tasks/|orchestrator/[^/]+_test\.py|templates/starter/.*(\.test\.|\.spec\.|/tests?/))")


SMOKE_DIFF_RE = re.compile(r"^agents/smoke/fixtures/[^/]+\.diff$")


SMOKE_EXPECTED = "agents/smoke/expected.json"


# Emphasis a prompt change must not add: a louder sentence is not a fix, and a model that was told so still adds it.
EMPHASIS_RE = re.compile(r"\b(CRITICAL|WARNING|ACTION REQUIRED|IMPORTANT|MUST NOT|MUST)\b|\u26a0|\*\*(CRITICAL|WARNING|IMPORTANT)")


APP_PATH_RE = re.compile(r"^diff --git a/(backend|frontend)/", re.M)


def added_lines(patch_text):
    # The lines a unified diff adds (not the `+++` file headers).
    return [l[1:] for l in patch_text.splitlines() if l.startswith("+") and not l.startswith("+++")]


def adds_emphasis(patch_text):
    # True if a diff of agents/prompts/*.md adds shouting (CRITICAL, WARNING, MUST, a warning sign...). Only the
    # added lines count, so a prompt that already says MUST somewhere is not blamed for it.
    return any(EMPHASIS_RE.search(l) for l in added_lines(patch_text))


def bad_fixture_reason(fixture_diffs):
    # Why new reviewer smoke fixtures cannot be used, or None. `fixture_diffs` maps each new
    # agents/smoke/fixtures/*.diff path to its text. The reviewer is shown a Managed App's change, so a fixture that is
    # not a diff of app code (for example a diff of a Factory prompt) tests nothing the reviewer ever sees.
    for path, text in fixture_diffs.items():
        if not APP_PATH_RE.search(text):
            return f"{path} is not a diff of Managed App code (it must change files under backend/ or frontend/)"
    return None


def lesson_has_fixture(paths):
    # True when a change set includes a test, smoke case or replay case alongside the fix.
    # A reviewer smoke fixture only counts as a pair: the diff the reviewer is shown and its expected.json entry. The
    # harness runs every fixtures/*.diff, so stray files in that folder would exercise nothing.
    if any(SMOKE_DIFF_RE.match(p) for p in paths) and SMOKE_EXPECTED in paths:
        return True
    return any(FIXTURE_RE.match(p) for p in paths)


def auto_merge_eligible(numstat):
    # `git diff --numstat` lines -> True only if every changed file is lint/formatter config in the
    # Starter Template and nothing was deleted (the change can only add or tighten a check).
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


def open_learning_prs(repo, token):
    out = tracker.gh(["pr", "list", "--repo", repo, "--state", "open", "--json", "headRefName"], token).stdout
    return sum(1 for p in json.loads(out or "[]") if p["headRefName"].startswith("learning/"))


def rejected_proposal(factory, paths):
    # The guardrails that look at what the Agent actually changed. Returns the reason to discard it, or None.
    prompts = [p for p in paths if p.startswith("agents/prompts/") and p.endswith(".md")]
    if prompts:
        patch_text = sh(["git", "diff", "HEAD", "--", *prompts], cwd=factory).stdout
        if adds_emphasis(patch_text):
            return "it adds emphasis (CRITICAL, WARNING, MUST, a warning sign) to a prompt; if a rule was missed, the fix is a check or a different cause, not a louder sentence"
    fixtures = [p for p in paths if re.match(r"^agents/smoke/fixtures/[^/]+\.diff$", p)]
    texts = {p: (Path(factory) / p).read_text() for p in fixtures if (Path(factory) / p).exists()}
    return bad_fixture_reason(texts)


def open_pr(factory, repo, pat, issue_no, result, run_id, max_open=3):
    # Validate what the Agent changed, test it, and open a PR. Returns the PR URL or None.
    # The PR is labelled `auto-merge-candidate` only for an additive lint/formatter change; the PR checks
    # workflow recomputes that and merges after its checks pass. Everything else waits for a human.
    changed = [l[3:].strip() for l in sh(["git", "status", "--porcelain"], cwd=factory).stdout.splitlines() if l]
    bad = [c for c in changed if not agent_run.allowed_path(c)]
    for c in bad:  # drop anything outside the allowed paths rather than refusing the whole proposal
        sh(["git", "checkout", "--", c], cwd=factory, check=False)
        sh(["git", "clean", "-fdq", "--", c], cwd=factory, check=False)
    keep = [c for c in changed if c not in bad]
    if not keep:
        return None
    bad = rejected_proposal(factory, keep)
    if bad:
        log(f"retrospective proposal rejected: {bad}")
        tracker.gh(["issue", "comment", str(issue_no), "--repo", repo, "--body",
            f"The retrospective Agent's proposed change was discarded by the guardrails: {bad}. No PR was opened."], pat)
        for c in keep:  # leave the checkout clean for whatever runs next
            sh(["git", "checkout", "--", c], cwd=factory, check=False)
            sh(["git", "clean", "-fdq", "--", c], cwd=factory, check=False)
        return None
    if open_learning_prs(repo, pat) >= max_open:
        log(f"{max_open} learning PRs are already open; not opening another")
        return None
    root = agent_run.scratch_root()
    try:
        passed = agent_run.run_tests(factory, root, agent_run.agent_user())
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if not passed:
        log("retrospective proposal breaks the orchestrator tests; not opening a PR")
        return None
    branch = f"learning/run-{run_id}"
    for cmd in (["git", "checkout", "-q", "-b", branch], ["git", "config", "user.name", "ai-factory-retrospective"],
                ["git", "config", "user.email", "retrospective@ai-factory.local"], ["git", "add", "--", *keep],
                ["git", "commit", "-qm", f"Retrospective fix: {result.get('change_summary', 'proposed change')[:70]}\n\nFor #{issue_no}."]):
        sh(cmd, cwd=factory)
    auth = "AUTHORIZATION: basic " + __import__("base64").b64encode(f"x-access-token:{pat}".encode()).decode()
    sh(["git", "push", "-q", "origin", branch], cwd=factory, env={**os.environ, **github.git_auth_env(auth)})
    numstat = sh(["git", "diff", "--numstat", "HEAD~1", "HEAD"], cwd=factory).stdout
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
        tracker.gh(["label", "create", "auto-merge-candidate", "--repo", repo, "--color", "0e8a16", "--description", "Merges itself after the PR checks pass"], pat)
        label = ["--label", "auto-merge-candidate"]
    out = tracker.gh(["pr", "create", "--repo", repo, "--head", branch, "--base", "main", "--title",
              f"Retrospective fix for #{issue_no}", "--body", body, *label], pat).stdout.strip()
    return out or None


def propose(factory, cfg, repo, pat, token, parent_key, facts_path, result_path, targets, run_id):
    # Run the Agent once for these lesson issues, comment its analysis on each, and open the PR.
    key, budget = agent_run.mint_agent(cfg, parent_key)
    if not key:
        return None
    result_path.unlink(missing_ok=True)
    ran = agent_run.run_agent(factory, cfg, key, facts_path, result_path, int(cfg["limits"].get("retrospective_timeout_minutes", 15)))
    agent_run.record_agent_spend(budget, key, repo, token, run_id)
    if not ran:
        return None
    result = agent_output.load_json(result_path) or {}
    if result.get("category") not in agent_run.CATEGORIES:
        for n in targets:
            tracker.gh(["issue", "comment", str(n), "--repo", repo, "--body", "The retrospective Agent produced no usable analysis."], token)
        return None
    pr = open_pr(factory, repo, pat, targets[0], result, run_id, int(cfg["limits"].get("max_open_learning_prs", 3)))
    for n in targets:
        tracker.gh(["issue", "comment", str(n), "--repo", repo, "--body",
            f"**Retrospective** ({result['category']}): {result.get('root_cause', '')}\n\n"
            f"**Proposed change**: {result.get('change_summary', 'none')}\n\n"
            + (f"**PR**: {pr}" if pr else "No change was proposed, it did not pass validation, or too many learning PRs are open.")], token)
    return result


def auto_merge_check(base, head):
    # Exit 0 only if the diff base...head is an additive lint/formatter change. The PR checks workflow
    # calls this before merging a PR labelled `auto-merge-candidate`; it does not trust the label.
    numstat = sh(["git", "diff", "--numstat", f"{base}...{head}"], cwd=config.FACTORY_DIR).stdout
    ok = auto_merge_eligible(numstat)
    print("auto-merge eligible" if ok else "not eligible for auto-merge (a human merges this)")
    return 0 if ok else 1
