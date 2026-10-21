import json
import os
import sys

from request import check_target_app, intake_labels, read_form
from shared import child_tickets, github

from build_run import read_child


class Refused(Exception):
    pass


def request_problem(body):
    change = read_form.form_section(body, "What should change?")
    return None if change and change != "_No response_" else 'the "What should change?" field is empty.'


def require_factory_app(owner, app, repo, pat):
    info = github.run(["api", f"repos/{owner}/{app}"], pat)
    if info.returncode != 0:
        raise Refused(f"`{owner}/{app}` does not exist. An update Intake changes an app the Factory already built; a new app starts with an Intake.")
    if not check_target_app.is_factory_repo(json.loads(info.stdout).get("description"), repo):
        raise Refused(f"`{owner}/{app}` was not created by this Factory (its description is not an `Intake: {repo}#<n>` marker), so the Factory will not change it.")


def planned_problem(repo, number, pat, body):
    try:
        return read_child.planned_problem(child_tickets.read_marker(body), child_tickets.parent_info(repo, number, pat))
    except child_tickets.ChildTicketError as e:
        return f"the plan could not be looked up ({e})"


def check_request(repo, owner, number, pat, body):
    try:
        app = read_form.app_name(body)
    except ValueError as e:
        raise Refused(str(e))
    if request_problem(body):
        raise Refused(request_problem(body))
    require_factory_app(owner, app, repo, pat)
    problem = planned_problem(repo, number, pat, body)
    if problem:
        raise Refused(f"this is not a planned child: {problem}.")
    return app


def refuse(why, repo, number, token, run_url):
    text = f"**Update App Intake stopped:** {why}\n\nFix this, then add the `{intake_labels.START}` label again to start. ([run]({run_url}))"
    github.run(["issue", "comment", number, "--repo", repo, "--body", text], token)
    github.run(["issue", "edit", number, "--repo", repo, "--remove-label", intake_labels.START], token)
    print(f"::error::{why}")
    return 1


def dispatch_build(repo, app, number, pat, token, run_url):
    github.ensure_label(repo, f"app:{app}", pat, "1d76db", f"Issues about the Managed App {app}")
    github.run(["issue", "edit", number, "--repo", repo, "--add-label", f"app:{app}"], pat, check=True)
    github.run(["workflow", "run", "build-run.yml", "--repo", repo, "-f", f"issue_number={number}", "-f", f"app_name={app}"], pat, check=True)
    accepted = (f"**Update App Intake accepted.** A Build Run for `{app}` has been dispatched: it codes, tests and reviews the change, "
                f"and releases it behind its flag only when everything passes. ([run]({run_url}))")
    github.run(["issue", "comment", number, "--repo", repo, "--body", accepted], token)


def start():
    repo, pat, token = os.environ["FACTORY_REPO"], os.environ["FACTORY_PAT"], os.environ["GH_TOKEN"]
    number, body, run_url = os.environ["ISSUE_NUMBER"], os.environ.get("ISSUE_BODY", ""), os.environ.get("RUN_URL", "")
    try:
        app = check_request(repo, repo.split("/")[0], number, pat, body)
    except Refused as why:
        return refuse(str(why), repo, number, token, run_url)
    dispatch_build(repo, app, number, pat, token, run_url)
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "start":
        return start()
    print("usage: python -m build_run.start_build start", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
