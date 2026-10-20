# What a child ticket says: the task text for one change set, the whole issue body (the Update App Intake form fields plus the marker), and a title line.

from shared import child_tickets


def one_line(text, limit=80):
    return " ".join(str(text).split())[:limit]


def render_change_set_task(cs, request=None, parent=None):
    # The task text for one change set: what the coder, tester and reviewer are given as the spec.
    lines = [f"Change set {cs['id']}: {cs['title']}", ""]
    if parent:
        lines += [f"Part of a larger request, planned in #{parent}. Do only this change set.", ""]
    if request:
        lines += ["The original request, for context only (do just this change set):", "", request.strip(), ""]
    lines += ["Acceptance criteria:"] + [f"- {c}" for c in cs.get("criteria", [])]
    lines += ["", "How each will be checked:"] + [f"- {v}" for v in cs.get("verification", [])]
    if cs.get("out_of_scope"):
        lines += ["", "Out of scope:"] + [f"- {o}" for o in cs["out_of_scope"]]
    if cs.get("flag"):
        slug = child_tickets.FLAG_SLOT if cs["flag"] is True else cs["flag"]
        lines += ["", f"Put the whole change behind one feature flag with the slug `{slug}`."]
    else:
        lines += ["", "Users cannot see or reach any difference from this change, so it needs no flag: do not add one, and do not put "
                      "anything that is live now behind a new flag."]
    return "\n".join(lines).strip()


def child_body(app, task, parent, cs, cap=None, secrets=None, kind="update"):
    # A child issue's body: the marker, then the Update App Intake form fields, so the child reads like any Update App Intake.
    # The marker goes first: text after the last "### " heading would be read as part of that field.
    meta = child_tickets.marker_for(cs, parent, kind, secrets)
    return (f"{child_tickets.render_marker(meta)}\n\n"
            f"### App name\n\n{app}\n\n### What should change?\n\n{task}\n\n### Cost cap override (USD)\n\n{cap if cap else '_No response_'}\n")
