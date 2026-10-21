import json
import os
import re
import shutil
from pathlib import Path

from shared import agent_output, config, github
from shared.console import log
from shared.shell import sh
from try_fix import factory_fix_request, route

from retrospective import agent_run, tracker

AUTO_MERGE_RE = re.compile(r"^templates/starter/(\.eslintrc[^/]*|eslint\.config\.[cm]?[jt]s|\.prettierrc[^/]*|"
                           r"prettier\.config\.[cm]?[jt]s|\.editorconfig)$")


FIXTURE_RE = re.compile(r"^(agents/replay/cases\.json|agents/lint-fixtures/|agents/smoke-coder/tasks/|orchestrator/[^/]+_test\.py|templates/starter/.*(\.test\.|\.spec\.|/tests?/))")


SMOKE_DIFF_RE = re.compile(r"^agents/smoke/fixtures/[^/]+\.diff$")


SMOKE_EXPECTED = "agents/smoke/expected.json"


EMPHASIS_RE = re.compile(r"\b(CRITICAL|WARNING|ACTION REQUIRED|IMPORTANT|MUST NOT|MUST)\b|\u26a0|\*\*(CRITICAL|WARNING|IMPORTANT)")


APP_PATH_RE = re.compile(r"^diff --git a/(backend|frontend)/", re.M)


def added_lines(patch_text):
    return [l[1:] for l in patch_text.splitlines() if l.startswith("+") and not l.startswith("+++")]


def adds_emphasis(patch_text):
    return any(EMPHASIS_RE.search(l) for l in added_lines(patch_text))


def bad_fixture_reason(fixture_diffs):
    for path, text in fixture_diffs.items():
        if not APP_PATH_RE.search(text):
            return f"{path} is not a diff of Managed App code (it must change files under backend/ or frontend/)"
    return None


def lesson_has_fixture(paths):
    if any(SMOKE_DIFF_RE.match(p) for p in paths) and SMOKE_EXPECTED in paths:
        return True
    return any(FIXTURE_RE.match(p) for p in paths)


def auto_merge_eligible(numstat):
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
    prompts = [p for p in paths if p.startswith("agents/prompts/") and p.endswith(".md")]
    if prompts:
        patch_text = sh(["git", "diff", "HEAD", "--", *prompts], cwd=factory).stdout
        if adds_emphasis(patch_text):
            return "it adds emphasis (CRITICAL, WARNING, MUST, a warning sign) to a prompt; if a rule was missed, the fix is a check or a different cause, not a louder sentence"
    fixtures = [p for p in paths if re.match(r"^agents/smoke/fixtures/[^/]+\.diff$", p)]
    texts = {p: (Path(factory) / p).read_text() for p in fixtures if (Path(factory) / p).exists()}
    return bad_fixture_reason(texts)


def open_pr(factory, repo, pat, issue_no, result, run_id, max_open=3, failed_child=None):
    changed = [l[3:].strip() for l in sh(["git", "status", "--porcelain"], cwd=factory).stdout.splitlines() if l]
    bad = [c for c in changed if not agent_run.allowed_path(c)]
    for c in bad:
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
        for c in keep:
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
    if failed_child:
        body += factory_fix_request.failed_child_marker(failed_child) + "\n"
    label = []
    if auto:
        tracker.gh(["label", "create", "auto-merge-candidate", "--repo", repo, "--color", "0e8a16", "--description", "Merges itself after the PR checks pass"], pat)
        label = ["--label", "auto-merge-candidate"]
    out = tracker.gh(["pr", "create", "--repo", repo, "--head", branch, "--base", "main", "--title",
              f"Retrospective fix for #{issue_no}", "--body", body, *label], pat).stdout.strip()
    return out or None


def propose(factory, cfg, repo, pat, token, parent_key, facts_path, result_path, targets, run_id, failed=None):
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
    cause = route.inferred_category(result.get("category"), failed["outcome"], failed["has_bugs"]) if failed else None
    resumes = failed["child"] if failed and route.route(cause) == "factory" else None
    pr = open_pr(factory, repo, pat, targets[0], result, run_id, int(cfg["limits"].get("max_open_learning_prs", 3)), resumes)
    for n in targets:
        tracker.gh(["issue", "comment", str(n), "--repo", repo, "--body",
            f"**Retrospective** ({result['category']}): {result.get('root_cause', '')}\n\n"
            f"**Proposed change**: {result.get('change_summary', 'none')}\n\n"
            + (f"**PR**: {pr}" if pr else "No change was proposed, it did not pass validation, or too many learning PRs are open.")], token)
    return result


def auto_merge_check(base, head):
    numstat = sh(["git", "diff", "--numstat", f"{base}...{head}"], cwd=config.FACTORY_DIR).stdout
    ok = auto_merge_eligible(numstat)
    print("auto-merge eligible" if ok else "not eligible for auto-merge (a human merges this)")
    return 0 if ok else 1
