import re

NUMBERED = re.compile(r"^\s*\d+\.\s+(.+?)\s*$")


def section_lines(ticket, heading):
    after = ticket.split(f"#### {heading}", 1)
    return after[1].split("\n#### ", 1)[0].splitlines() if len(after) == 2 else []


def requirements_of(ticket):
    return [m.group(1) for m in map(NUMBERED.match, section_lines(ticket, "Requirements")) if m]


def title_of(ticket):
    happened = next((line.strip() for line in section_lines(ticket, "What happened") if line.strip()), "")
    return f"Fix: {happened[:80]}" if happened else "Fix"


def plan_from_ticket(ticket):
    reqs = requirements_of(ticket)
    change_set = {"id": "CS-1", "title": title_of(ticket), "requirements": [f"REQ-{i}" for i in range(1, len(reqs) + 1)], "depends_on": [],
                  "criteria": reqs, "verification": ["Check each requirement on the running app and run the tests"], "size": "S", "flag": True, "internal_only": False, "out_of_scope": []}
    return {"feasibility": {"status": "ok"}, "requirements": [{"id": f"REQ-{i}", "text": r} for i, r in enumerate(reqs, 1)], "assumptions": [],
            "open_questions": [], "secrets": [], "change_sets": [change_set]}
