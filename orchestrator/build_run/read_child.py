# Reading the child a Build Run was dispatched with: its request text and cost cap from the body, and whether it is an Update App Intake with a plan marker.
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
    # (is an Update App Intake, its plan metadata) for the issue a Build Run was dispatched with, or NeedsHuman if the issue
    # does not belong to `app`. A new app's Intake is titled with the app's name. An Update App Intake has a free title,
    # names the app in its form, and carries the `app:<slug>` label that Update App Intake adds after checking the repo.
    labels = {l["name"] for l in issue.get("labels", [])}
    body = issue.get("body") or ""
    if intake_labels.UPDATE_APP_INTAKE not in labels:
        if issue["title"].strip() != app:
            raise run_stops.NeedsHuman("other", f"Intake #{number} is titled {issue['title']!r}, not {app!r}.")
        return False, {}
    try:
        named = read_form.app_name(body)
    except ValueError as e:
        raise run_stops.NeedsHuman("other", f"Update App Intake #{number}: {e}.")
    if named != app or f"app:{app}" not in labels:
        raise run_stops.NeedsHuman("other", f"Update App Intake #{number} names {named!r} and is labelled "
                                  f"{sorted(l for l in labels if l.startswith('app:'))}, not {app!r}.")
    return True, child_tickets.read_marker(body)
