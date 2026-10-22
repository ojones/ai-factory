import json

from shared import github

LABEL = "factory-change-paused"
IN_A_ROW = 2


def is_paused(repo, token):
    found = github.run(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--json", "number"], token).stdout
    return bool(json.loads(found or "[]"))


def breaker_reason(watched_stage, later_runs, ineffective_in_a_row):
    for run in later_runs:
        if run.get("regression"):
            return "a canary or benchmark regression followed the merge"
        if run.get("failed") and run.get("stage") == watched_stage:
            return f"a Build Run failed at the same stage ({watched_stage}) after the merge"
    if ineffective_in_a_row >= IN_A_ROW:
        return f"{ineffective_in_a_row} merged changes in a row were tagged fix-ineffective"
    return None


def pause(repo, token, reason, pr_url=""):
    github.ensure_label(repo, LABEL, token, "b60205", "The Factory Change process is paused until a person clears this label")
    return github.run(["issue", "create", "--repo", repo, "--label", LABEL, "--title", "Factory Change paused",
                       "--body", f"Factory Changes are paused: {reason}.\n\n{pr_url}\n\nClose this issue or remove the label to resume."], token)

