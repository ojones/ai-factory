import json
import os
import shlex
import sys

from request import intake_labels, read_form
from shared import child_tickets, config, github


class NotStageable(Exception):
    pass


def check_child(child, parent, parent_issue, in_flight, build_runs_running, max_apps, limits):
    marker = child_tickets.read_marker(child["body"])
    if marker.get("kind") != "staging":
        raise NotStageable("this child is not a staging child (its plan marker does not say `kind: staging`), so there is no app to stage for it")
    if not parent:
        raise NotStageable("this staging child is not a sub-issue of any Intake, so there is no request to stage an app for")
    if marker.get("parent") != parent["number"]:
        raise NotStageable(f"its plan marker names #{marker.get('parent')} but it is a sub-issue of #{parent['number']}")
    if parent["state"] != "OPEN":
        raise NotStageable(f"its Intake (#{parent['number']}) is closed; reopen it, or file a new request")
    try:
        app = read_form.app_name(child["body"])
        description, cap = read_form.read_request(parent_issue["body"], limits["cost_cap_usd_default"], limits["cost_cap_usd_ceiling"])
    except ValueError as e:
        raise NotStageable(str(e))
    if in_flight:
        raise NotStageable("staging child(ren) " + ", ".join(f"#{n}" for n in in_flight) + f" are already being staged; the limit is {max_apps} "
                           "Managed App(s) through staging at a time (`max_simultaneous_build_runs` in agents/profiles.yml)")
    if build_runs_running >= max_apps:
        raise NotStageable(f"{build_runs_running} Build Run(s) are in flight; the limit is {max_apps} at a time (`max_simultaneous_build_runs` in agents/profiles.yml)")
    raw = read_form.form_section(parent_issue["body"], "Cost cap override (USD)").lstrip("$")
    return {"app": app, "parent": parent["number"], "description": description, "cost_cap": f"{cap:.2f}",
            "cap_source": "override" if raw and raw != read_form.NO_ANSWER else "default"}


def staging_children_in_flight(issues, this):
    return sorted(i["number"] for i in issues if i["number"] != this and child_tickets.read_marker(i.get("body")).get("kind") == "staging")


def shell_lines(found):
    return [f"{key}={shlex.quote(str(value))}" for key, value in (("SLUG", found["app"]), ("PARENT", found["parent"]), ("DESCRIPTION", found["description"]),
                                                                   ("COST_CAP", found["cost_cap"]), ("CAP_SOURCE", found["cap_source"]))]


def main():
    e = os.environ
    repo, number, token = e["FACTORY_REPO"], int(e["ISSUE_NUMBER"]), e["GH_TOKEN"]

    def gh_json(args):
        p = github.run(args, token)
        if p.returncode != 0:
            raise NotStageable(f"GitHub refused `gh {' '.join(args[:3])}`: {(p.stderr or '').strip()[:200]}")
        return json.loads(p.stdout or "null")

    try:
        child = gh_json(["issue", "view", str(number), "--repo", repo, "--json", "number,body,labels"])
        parent = child_tickets.parent_info(repo, number, token)
        parent_issue = gh_json(["issue", "view", str(parent["number"]), "--repo", repo, "--json", "body"]) if parent else {"body": ""}
        limits = config.load()["limits"]
        max_apps = int(limits.get("max_simultaneous_build_runs", 1) or 1)
        started = gh_json(["issue", "list", "--repo", repo, "--state", "open", "--label", intake_labels.START, "--limit", "100", "--json", "number,body"])
        running = 0
        for status in ("queued", "in_progress"):
            running += len(gh_json(["run", "list", "--repo", repo, "--workflow", "build-run.yml", "--status", status, "--json", "url"]))
        found = check_child(child, parent, parent_issue, staging_children_in_flight(started, number), running, max_apps, limits)
    except (NotStageable, child_tickets.ChildTicketError) as ex:
        print(str(ex), file=sys.stderr)
        return 3
    print("\n".join(shell_lines(found)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
