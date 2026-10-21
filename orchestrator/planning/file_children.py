from request import intake_labels
from shared import child_tickets, github

from planning.render_child import child_body, one_line, render_change_set_task

INHERITED = ("benchmark",)


CHILD_LABELS = {"update": intake_labels.UPDATE_APP_INTAKE, "factory": intake_labels.FACTORY_CHILD}


def ensure_child_labels(repo, pat, app, inherit, kind="update"):
    for name in inherit:
        github.ensure_label(repo, name, pat, "ededed", "Inherited from the Intake")
    for name, color, desc in ((CHILD_LABELS[kind], "1d76db", "A change request for an existing Managed App or the Factory"),
                              (child_tickets.WAIT, "fbca04", "Waiting for an earlier change set of the same plan"),
                              (intake_labels.START, "0e8a16", "Start this change now"), (f"app:{app}", "1d76db", f"Issues about the Managed App {app}")):
        github.ensure_label(repo, name, pat, color, desc)


def file_one_child(tickets, app, parent, cs, cap, secrets, fix, inherit, kind="update"):
    body = child_body(app, render_change_set_task(cs, parent=parent), parent, cs, cap, secrets, kind if kind == "factory" else cs.get("kind") or "update",
                      fix_for=fix["fix_for"] if fix else None, fix_attempt=fix["attempt"] if fix else None)
    return tickets.file(f"{app}: {one_line(cs['title'])}", body, [CHILD_LABELS[kind], f"app:{app}", child_tickets.WAIT, *inherit])


def file_in_order(tickets, app, parent, by_id, order, cap, secrets, fix, inherit, kind):
    numbers, made = {}, []
    try:
        for cs_id in order:
            cs = by_id[cs_id]
            blockers = [numbers[d] for d in cs.get("depends_on") or []]
            numbers[cs_id] = file_one_child(tickets, app, parent, cs, cap, secrets, fix, inherit, kind)
            made.append((cs_id, numbers[cs_id]))
            for blocker in blockers:
                tickets.block(numbers[cs_id], blocker)
    except child_tickets.ChildTicketError:
        for _, number in made:
            tickets.withdraw(number, "Closed: the plan could not be filed completely, so no child of it will run. Plan the Intake again.")
        raise
    return made


def file_children(repo, pat, app, parent, change_sets, order, request, cap=None, secrets=None, tickets=None, fix=None, inherit=(), kind="update"):
    tickets = tickets or child_tickets.ChildTickets(repo, parent, pat)
    existing = tickets.children()
    if existing:
        return [(c["marker"].get("cs"), c["number"]) for c in existing]
    ensure_child_labels(repo, pat, app, inherit, kind)
    by_id = {cs["id"]: cs for cs in change_sets}
    made = file_in_order(tickets, app, parent, by_id, order, cap, secrets, fix, inherit, kind)
    first = next((cs_id for cs_id in order if not by_id[cs_id].get("depends_on")), None)
    if first:
        github.run(["issue", "edit", str(dict(made)[first]), "--repo", repo, "--remove-label", child_tickets.WAIT, "--add-label", intake_labels.START], pat)
    return made
