# The gate that starts a Build Run for a child (STEP 4.1's trigger): a change request for a Managed App that already exists.
#
# An update Intake is a GitHub issue made from the "Update App Intake" form (label `update-app-intake`). Adding the label
# `proceed-with-change` starts it at once: `.github/workflows/update-app-intake.yml` runs `start`, which checks the issue
# and dispatches a Build Run. There is no App Staging; the app, its repo and its flags already exist.
#
# The Build Run then plans (agents/prompts/planner.md), and if the plan is one change set it codes, tests, reviews and
# releases that change. If the plan has several change sets, the Build Run files one child issue per change set
# (planning/file_children.py: sub-issues of the Intake, blocked by their dependencies; labels `update-app-intake`, `app:<slug>`, `plan:<parent>`) and ends. The first child with nothing to wait for gets
# `proceed-with-change` straight away; the others get `waiting-on-plan`. When a child's Build Run succeeds, `retrospective/close_child.py`
# gives `proceed-with-change` to the next sibling whose blockers are all closed (one at a time). So the children run one after
# another, never two pending runs of one app at once (GitHub keeps only one pending run per concurrency group).
#
# The label is added with the PAT, not the Actions token: events made by the Actions token do not start workflows.
#
# Commands (env: GH_TOKEN, FACTORY_PAT, FACTORY_REPO, ISSUE_NUMBER, ISSUE_BODY, RUN_URL):
#   start     validate the issue, label it app:<slug>, dispatch the Build Run
#
# Usage: python -m build_run.start_build start   (PYTHONPATH=orchestrator)
import json
import os
import sys

from request import check_target_app, intake_labels, read_form
from shared import github


def start():
    repo, pat, token = os.environ["FACTORY_REPO"], os.environ["FACTORY_PAT"], os.environ["GH_TOKEN"]
    number, body, run_url = os.environ["ISSUE_NUMBER"], os.environ.get("ISSUE_BODY", ""), os.environ.get("RUN_URL", "")
    owner = repo.split("/")[0]

    def refuse(why):
        github.run(["issue", "comment", number, "--repo", repo, "--body",
            f"**Update App Intake stopped:** {why}\n\nFix this, then add the `{intake_labels.START}` label again to start. ([run]({run_url}))"], token)
        github.run(["issue", "edit", number, "--repo", repo, "--remove-label", intake_labels.START], token)
        print(f"::error::{why}")
        return 1

    try:
        app = read_form.app_name(body)
    except ValueError as e:
        return refuse(str(e))
    if not read_form.form_section(body, "What should change?") or read_form.form_section(body, "What should change?") == "_No response_":
        return refuse('the "What should change?" field is empty.')
    info = github.run(["api", f"repos/{owner}/{app}"], pat)
    if info.returncode != 0:
        return refuse(f"`{owner}/{app}` does not exist. An update Intake changes an app the Factory already built; a new app starts with an Intake.")
    if not check_target_app.is_factory_repo(json.loads(info.stdout).get("description"), repo):
        return refuse(f"`{owner}/{app}` was not created by this Factory (its description is not an `Intake: {repo}#<n>` marker), so the Factory will not change it.")
    github.ensure_label(repo, f"app:{app}", pat, "1d76db", f"Issues about the Managed App {app}")
    github.run(["issue", "edit", number, "--repo", repo, "--add-label", f"app:{app}"], pat, check=True)
    github.run(["workflow", "run", "build-run.yml", "--repo", repo, "-f", f"issue_number={number}", "-f", f"app_name={app}"], pat, check=True)
    github.run(["issue", "comment", number, "--repo", repo, "--body",
        f"**Update App Intake accepted.** A Build Run for `{app}` has been dispatched: it plans the change, then codes, tests and reviews it, "
        f"and releases it behind its flag only when everything passes. ([run]({run_url}))"], token)
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "start":
        return start()
    print("usage: python -m build_run.start_build start", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
