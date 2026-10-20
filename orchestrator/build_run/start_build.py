# The gate that starts a Build Run for a child ticket (STEP 4.1's trigger). Planning (`planning/plan_run.py`) files each Intake's change sets as child tickets,
# sub-issues of the Intake carrying a `factory-plan` marker, and puts `proceed-with-change` on the first child with nothing to wait for; the rest are
# labelled `waiting-on-plan`, and `retrospective/close_child.py` gives `proceed-with-change` to the next one whose blockers are closed, one at a time, so an app
# never has two pending Build Runs (GitHub keeps only one pending run per concurrency group). A staging child is staged by App Staging instead.
#
# `.github/workflows/update-app-intake.yml` runs `start`, which refuses (comments, removes the label) anything that is not a planned child of an open plan,
# or whose app is not one this Factory built, and otherwise labels it app:<slug> and dispatches the Build Run.
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
from shared import child_tickets, github

from build_run import read_child


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
    # Only a planned child starts a run: a sub-issue of an open plan whose body carries the `factory-plan` marker naming that plan.
    try:
        problem = read_child.planned_problem(child_tickets.read_marker(body), child_tickets.parent_info(repo, number, pat))
    except child_tickets.ChildTicketError as e:
        problem = f"the plan could not be looked up ({e})"
    if problem:
        return refuse(f"this is not a planned child: {problem}.")
    github.ensure_label(repo, f"app:{app}", pat, "1d76db", f"Issues about the Managed App {app}")
    github.run(["issue", "edit", number, "--repo", repo, "--add-label", f"app:{app}"], pat, check=True)
    github.run(["workflow", "run", "build-run.yml", "--repo", repo, "-f", f"issue_number={number}", "-f", f"app_name={app}"], pat, check=True)
    github.run(["issue", "comment", number, "--repo", repo, "--body",
        f"**Update App Intake accepted.** A Build Run for `{app}` has been dispatched: it codes, tests and reviews the change, "
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
