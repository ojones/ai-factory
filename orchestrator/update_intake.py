#!/usr/bin/env python3
# Update App Intake: a change request for a Managed App that already exists.
#
# An update Intake is a GitHub issue made from the "Update App Intake" form (label `update-app-intake`). Adding the label
# `proceed-with-change` starts it at once: `.github/workflows/update-app-intake.yml` runs `start`, which checks the issue
# and dispatches a Build Run. There is no App Staging; the app, its repo and its flags already exist.
#
# The Build Run then plans (agents/prompts/planner.md), and if the plan is one change set it codes, tests, reviews and
# releases that change. If the plan has several change sets, the Build Run files one child issue per change set
# (planning/file_children.py: sub-issues of the Intake, blocked by their dependencies; labels `update-app-intake`, `app:<slug>`, `plan:<parent>`) and ends. The first child with nothing to wait for gets
# `proceed-with-change` straight away; the others get `waiting-on-plan`. When a child's Build Run succeeds, `advance`
# gives `proceed-with-change` to the next sibling whose dependencies are now all closed (one at a time). So the children run one after
# another, never two pending runs of one app at once (GitHub keeps only one pending run per concurrency group).
#
# The label is added with the PAT, not the Actions token: events made by the Actions token do not start workflows.
#
# Commands (env: GH_TOKEN, FACTORY_PAT, FACTORY_REPO, ISSUE_NUMBER, ISSUE_BODY, RUN_URL):
#   start     validate the issue, label it app:<slug>, dispatch the Build Run
#   advance   after a child's Build Run succeeded: release its dependents
import json
import os
import re
import sys

from request import check_target_app, intake_labels, read_form
from shared import child_tickets, github

WAIT = child_tickets.WAIT
FIX_RE = re.compile(r"<!-- factory-fix:(.*?) -->", re.S)
AUTO_FIX = "auto-fix"


# --- pure logic (unit-tested) -------------------------------------------------


def fix_meta(body):
    # The retry metadata hidden in an automatic fix request ({} for any other issue): which Intake it came from (`origin`),
    # which automatic attempt it is (`attempt`, 1 for the first) and what earlier attempts found (`history`).
    m = FIX_RE.search(body or "")
    if not m:
        return {}
    try:
        meta = json.loads(m.group(1))
        return meta if isinstance(meta, dict) else {}
    except ValueError:
        return {}


def with_fix_meta(meta):
    return f"<!-- factory-fix:{json.dumps(meta, separators=(',', ':')).replace('--', chr(92) + 'u002d' + chr(92) + 'u002d')} -->"


def ready_to_start(children):
    # The number of the one child to start now, as a list (empty when none). Each child is {number, state, labels,
    # depends_on}. It must be open, waiting, not already started, with every issue it depends on closed (an unknown
    # dependency counts as open). At most one is started, and none while another is open with `proceed-with-change`:
    # one app runs one Build Run at a time, and GitHub drops all but one pending run, so two started together would lose one.
    if any(c["state"].upper() == "OPEN" and intake_labels.START in c["labels"] for c in children):
        return []
    state = {c["number"]: c["state"].upper() for c in children}
    ready = [c["number"] for c in children
             if c["state"].upper() == "OPEN" and WAIT in c["labels"]
             and all(state.get(d) == "CLOSED" for d in c["depends_on"])]
    return sorted(ready)[:1]


# --- GitHub (not unit-tested) -------------------------------------------------


def siblings(repo, pat, parent):
    out = github.run(["issue", "list", "--repo", repo, "--label", f"plan:{parent}", "--state", "all", "--limit", "100",
              "--json", "number,state,labels,body"], pat).stdout
    return [{"number": i["number"], "state": i["state"], "labels": {l["name"] for l in i["labels"]},
             "depends_on": child_tickets.read_marker(i["body"]).get("depends_on", [])} for i in json.loads(out or "[]")]


def advance(repo, pat, number):
    # After child #number's Build Run succeeded and its issue is closed: start the siblings it was holding up.
    body = json.loads(github.run(["issue", "view", str(number), "--repo", repo, "--json", "body"], pat).stdout or "{}").get("body", "")
    parent = child_tickets.read_marker(body).get("parent")
    if not parent:
        return []
    started = ready_to_start(siblings(repo, pat, parent))
    for n in started:
        github.run(["issue", "edit", str(n), "--repo", repo, "--remove-label", WAIT, "--add-label", intake_labels.START], pat)
    return started


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
    if cmd == "advance":
        started = advance(os.environ["FACTORY_REPO"], os.environ["FACTORY_PAT"], os.environ["ISSUE_NUMBER"])
        print("started:", started)
        return 0
    print("usage: update_intake.py start|advance", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
