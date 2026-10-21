import json

from retrospective import learning_pr
from shared import github
from shared.shell import sh

from factory_change import markers, tiers

PR_LABEL = "factory-change-pr"
AUTO_LABEL = "factory-change-auto"
HOLD_LABEL = "awaiting-human"
BRANCH_PREFIX = "factory-change/"


def branch_of(child):
    return f"{BRANCH_PREFIX}{child}"


def open_count(repo, token):
    found = github.run(["pr", "list", "--repo", repo, "--state", "open", "--json", "headRefName"], token).stdout
    return sum(1 for p in json.loads(found or "[]") if p["headRefName"].startswith(BRANCH_PREFIX))


def pr_body(child, summary, reproduction, tier, paths):
    lines = [f"Factory Change for #{child}.", "", f"**Change**: {summary}", "", f"**Reproduction**: `{reproduction}`", f"**Tier**: {tier}", "", "Files:", *[f"- {p}" for p in paths], ""]
    markers_text = [markers.render(markers.CHILD, child), markers.render(markers.REPRODUCTION, reproduction), markers.render(markers.TIER, tier)]
    return "\n".join(lines + markers_text) + "\n"


def commit(factory, branch, child, summary):
    for cmd in (["git", "checkout", "-q", "-b", branch], ["git", "config", "user.name", "ai-factory-change"],
                ["git", "config", "user.email", "factory-change@ai-factory.local"], ["git", "add", "-A"],
                ["git", "commit", "-qm", f"Factory Change: {summary[:70]}\n\nFor #{child}."]):
        sh(cmd, cwd=factory)


def labels_for(tier):
    return [PR_LABEL, AUTO_LABEL if tier == tiers.TIER_ONE else HOLD_LABEL]


def ensure_labels(repo, pat):
    for name, color, desc in ((PR_LABEL, "5319e7", "A Factory Change pull request"), (AUTO_LABEL, "0e8a16", "Merges itself when the gates pass"),
                              (HOLD_LABEL, "fbca04", "Waits for a person to merge")):
        github.ensure_label(repo, name, pat, color, desc)


def open_pr(factory, repo, pat, child, summary, reproduction, paths, max_open):
    if open_count(repo, pat) >= max_open:
        return None
    tier = tiers.merge_tier(paths)
    branch = branch_of(child)
    commit(factory, branch, child, summary)
    learning_pr.push_branch(factory, branch, pat)
    ensure_labels(repo, pat)
    out = github.run(["pr", "create", "--repo", repo, "--head", branch, "--base", "main", "--title", f"Factory Change for #{child}: {summary[:60]}",
                      "--body", pr_body(child, summary, reproduction, tier, paths), *[f for name in labels_for(tier) for f in ("--label", name)]], pat)
    return (out.stdout or "").strip() or None
