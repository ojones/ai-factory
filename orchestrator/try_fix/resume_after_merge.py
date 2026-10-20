# STEP 7.4: when a learning PR that fixes a Factory cause merges, the child that failed because of it is started again with the PAT. The PR says which child
# (`failed-child` marker in its body). A child that is no longer waiting for this (closed, or already started) is left alone.
import json
import os
import sys

from request import intake_labels
from shared import github

from try_fix import factory_fix_request


def resume(repo, pat, token, pr_body):
    # Returns the number of the child that was started again, or None.
    number = factory_fix_request.read_failed_child(pr_body)
    if not number:
        return None
    child = json.loads(github.run(["issue", "view", str(number), "--repo", repo, "--json", "state,labels"], token).stdout or "{}")
    labels = {x["name"] for x in child.get("labels") or []}
    if str(child.get("state", "")).upper() != "OPEN" or intake_labels.START in labels or "needs-human" not in labels:
        return None
    github.run(["issue", "edit", str(number), "--repo", repo, "--remove-label", "needs-human"], token)
    github.run(["issue", "comment", str(number), "--repo", repo, "--body", "The fix for the Factory was merged, so this change set starts again."], token)
    github.run(["issue", "edit", str(number), "--repo", repo, "--add-label", intake_labels.START], pat)  # the PAT: the Actions token would not start the workflow
    return number


def main():
    e = os.environ
    started = resume(e["GITHUB_REPOSITORY"], e["FACTORY_PAT"], e["FACTORY_GH_TOKEN"], e.get("PR_BODY", ""))
    print(f"resumed #{started}" if started else "nothing to resume")
    return 0


if __name__ == "__main__":
    sys.exit(main())
