import re

from retrospective import learning_pr
from shared.shell import sh

from factory_change import tiers

CAP_LINE = re.compile(r"^\+\s*(model|fallback_model|\w*usd\w*|\w*cap\w*):", re.M)
EMPHASIS_REASON = "it adds emphasis (CRITICAL, WARNING, MUST, a warning sign) to a prompt; the fix for a missed rule is a check or a different cause, not a louder sentence"
TEST_FILE = re.compile(r"(^|/)[^/]+_test\.py$")


def stage_all(factory):
    sh(["git", "add", "-A"], cwd=factory)


def read_changes(factory, base="HEAD"):
    stage_all(factory)
    statuses = dict(reversed(line.split("\t", 1)) for line in sh(["git", "diff", "--name-status", base], cwd=factory).stdout.splitlines() if line)
    changes = {}
    for line in sh(["git", "diff", "--numstat", base], cwd=factory).stdout.splitlines():
        added, deleted, path = line.split("\t")
        changes[path] = {"status": statuses.get(path, "M")[0], "added": int(added) if added != "-" else 0, "deleted": int(deleted) if deleted != "-" else 0}
    return changes


def patches_of(factory, paths, base="HEAD"):
    return {p: sh(["git", "diff", base, "--", p], cwd=factory).stdout for p in paths}


def paths_with(changes, status):
    return [p for p, c in changes.items() if c["status"] == status]


def lost_tests(changes):
    gone = [p for p in paths_with(changes, "D") if TEST_FILE.search(p)]
    return gone if len(gone) > sum(1 for p in paths_with(changes, "A") if TEST_FILE.search(p)) else []


def size_problem(changes, limits):
    if len(changes) > int(limits["factory_change_max_files"]):
        return f"it changes {len(changes)} files, over the limit of {limits['factory_change_max_files']}"
    added = sum(c["added"] for c in changes.values())
    if added > int(limits["factory_change_max_added_lines"]):
        return f"it adds {added} lines, over the limit of {limits['factory_change_max_added_lines']}"
    return None


def scope_problem(changes):
    paths = list(changes)
    outside = [p for p in paths if tiers.classify(p) == tiers.NEVER]
    if outside:
        return f"it touches paths no Agent may change: {', '.join(outside)}"
    if tiers.mixes_tiers(paths):
        return "it mixes control-path files that wait for a person with files that merge on green; they belong in separate change sets"
    return None


def test_problem(changes):
    gone = lost_tests(changes)
    return f"it deletes tests without a replacement: {', '.join(gone)}" if gone else None


def patch_problem(patches):
    if CAP_LINE.search(patches.get("agents/profiles.yml", "")):
        return "it changes a model or a spending cap in agents/profiles.yml"
    prompts = "\n".join(text for path, text in patches.items() if tiers.PROMPT_PATH.fullmatch(path))
    return EMPHASIS_REASON if learning_pr.adds_emphasis(prompts) else None


def problem(changes, limits, patches=None):
    if not changes:
        return "it changes nothing"
    return scope_problem(changes) or size_problem(changes, limits) or test_problem(changes) or patch_problem(patches or {})
