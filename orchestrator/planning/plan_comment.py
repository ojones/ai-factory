# The plan as a comment on the Intake issue.
from planning.render_child import one_line


def render_plan_comment(plan, questions=()):
    # The plan as a comment on the Update App Intake: change sets with their flags, the assumptions the planner made on the
    # owner's behalf, and any question it needs answered. Anything the owner disagrees with can be corrected in the issue.
    sets = plan.get("change_sets") or []
    lines = [f"**Plan: {len(sets)} change set{'s' if len(sets) != 1 else ''}.**", ""]
    for cs in sets:
        flag = ("a flag named for its issue" if cs["flag"] is True else f"flag `{cs['flag']}`") if cs.get("flag") else "no flag (internal)"
        lines.append(f"- **{cs.get('id')}** {one_line(cs.get('title', ''), 120)} ({flag})")
    if plan.get("assumptions"):
        lines += ["", "**Assumptions I made for you** (not asked, because they looked low-impact; if one is wrong, the change is behind a flag and can be switched off, then fix the request here and add `proceed-with-change` again):"]
        lines += [f"- {one_line(a, 300)}" for a in plan["assumptions"]]
    if questions:
        lines += ["", "**I need an answer before building anything:**"] + [f"- {one_line(q, 400)}" for q in questions]
    return "\n".join(lines)
