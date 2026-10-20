# Reading the child a Build Run was dispatched with (STEP 4.1): its request text and cost cap from the body, its `factory-plan` marker, and whether it
# is really a planned child: a sub-issue of an open parent whose marker names that parent. The parent is read for its number and state only, never
# for instructions.
from request import intake_labels, read_form
from shared import (
    child_tickets,
    run_stops,
)


def parse_intake(body, default_cap, ceiling):
    try:
        return read_form.read_request(body, default_cap, ceiling)
    except ValueError as e:
        raise run_stops.NeedsHuman("other", str(e))


def identify_intake(issue, app, number):
    # The plan marker of the child a Build Run was dispatched with, or NeedsHuman if the issue is not a child ticket of `app`. A Build Run starts for a planned
    # child only: an issue labelled `update-app-intake` that names the app in its form and carries the `app:<slug>` label planning gave it.
    labels = {l["name"] for l in issue.get("labels", [])}
    body = issue.get("body") or ""
    if intake_labels.UPDATE_APP_INTAKE not in labels:
        raise run_stops.NeedsHuman("other", f"Issue #{number} is not a child ticket (it is not labelled `{intake_labels.UPDATE_APP_INTAKE}`): a Build Run starts for planned child tickets only.")
    try:
        named = read_form.app_name(body)
    except ValueError as e:
        raise run_stops.NeedsHuman("other", f"Child ticket #{number}: {e}.")
    if named != app or f"app:{app}" not in labels:
        raise run_stops.NeedsHuman("other", f"Child ticket #{number} names {named!r} and is labelled "
                                  f"{sorted(l for l in labels if l.startswith('app:'))}, not {app!r}.")
    return child_tickets.read_marker(body)


def planned_problem(marker, parent):
    # Why this child is not a planned one, or None. `parent` is {number, state} from the sub-issues API, or None for an issue with no parent.
    if marker.get("kind") == "staging":
        return "it is a staging child: App Staging stages and verifies the app, and no Build Run is started for it"
    if not marker:
        return "it has no plan marker: it was not planned (a child ticket is made by the planning process)"
    if not parent:
        return "it is not a sub-issue of any plan, so there is no plan for it to belong to"
    if marker.get("parent") != parent["number"]:
        return f"its plan marker names #{marker.get('parent')} but it is a sub-issue of #{parent['number']}"
    if parent["state"] != "OPEN":
        return f"its plan (#{parent['number']}) is closed; reopen the plan, or file a new request"
    return None


def require_planned(number, marker, parent):
    problem = planned_problem(marker, parent)
    if problem:
        raise run_stops.NeedsHuman("other", f"Update App Intake #{number} is not planned yet: {problem}.")
