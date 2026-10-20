# Filing a plan's child tickets: one sub-issue per change set under the Intake, each with its complete instructions and its marker, dependencies
# first, the dependencies as GitHub blockers. Filing is idempotent (a parent that already has children is left alone) and all-or-nothing (if any
# call fails, the children made so far are closed and the error is raised, so the Intake can be planned again with no orphans).
from request import intake_labels
from shared import child_tickets, github

from planning import fix_for
from planning.render_child import child_body, one_line, render_change_set_task

INHERITED = ("benchmark",)  # labels of the Intake that its children carry too


def file_children(repo, pat, app, parent, change_sets, order, request, cap=None, secrets=None, tickets=None, fix=None, inherit=()):
    # Returns [(change set id, issue number)]. Raises ChildTicketError. `fix` is the bug Intake's fix-for marker (planning/fix_for.py): the one child is filed
    # behind the failed story's flag with the markers that say so.
    tickets = tickets or child_tickets.ChildTickets(repo, parent, pat)
    existing = tickets.children()
    if existing:
        return [(c["marker"].get("cs"), c["number"]) for c in existing]
    for name in inherit:
        github.ensure_label(repo, name, pat, "ededed", "Inherited from the Intake")
    for name, color, desc in ((intake_labels.UPDATE_APP_INTAKE, "1d76db", "A change request for an existing Managed App"),
                              (child_tickets.WAIT, "fbca04", "Waiting for an earlier change set of the same plan"),
                              (intake_labels.START, "0e8a16", "Start this change now"), (f"app:{app}", "1d76db", f"Issues about the Managed App {app}")):
        github.ensure_label(repo, name, pat, color, desc)
    by_id = {cs["id"]: cs for cs in change_sets}
    numbers, made = {}, []
    try:
        for cs_id in order:
            cs = fix_for.apply(by_id[cs_id], fix)
            deps = [numbers[d] for d in cs.get("depends_on") or []]
            task = render_change_set_task(cs, parent=parent)
            body = child_body(app, task, parent, cs, cap, secrets, cs.get("kind") or "update", *((fix["flag_story"], fix["fix_for"], fix["attempt"]) if fix else ()))
            numbers[cs_id] = tickets.file(f"{app}: {one_line(cs['title'])}", body,
                                          [intake_labels.UPDATE_APP_INTAKE, f"app:{app}", child_tickets.WAIT, *inherit])
            made.append((cs_id, numbers[cs_id]))
            for dep in deps:
                tickets.block(numbers[cs_id], dep)
    except child_tickets.ChildTicketError:
        for _, number in made:
            tickets.withdraw(number, "Closed: the plan could not be filed completely, so no child of it will run. Plan the Intake again.")
        raise
    # Start the first one with nothing to wait for. Done last, so every child exists before the first run begins; the
    # rest are started one at a time by `advance` as each finishes.
    first = next((cs_id for cs_id in order if not by_id[cs_id].get("depends_on")), None)
    if first:
        github.run(["issue", "edit", str(numbers[first]), "--repo", repo, "--remove-label", child_tickets.WAIT, "--add-label", intake_labels.START], pat)
    return made
