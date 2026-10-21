import re

from request import render_form

from try_fix import validate_bug

MARKER = re.compile(r"<!-- bug:([0-9a-f]+) -->")
TARGET_TEXT = {"managed_app": "The Managed App (its code or its request).", "factory": "The Factory itself (a prompt, the planner, the Starter Template or the orchestrator)."}


def marker(key):
    return f"<!-- bug:{key} -->"


def read_key(body):
    m = MARKER.search(body or "")
    return m.group(1) if m else None


def title(verdict, app):
    return f"{app}: {verdict['event']['summary'][:80]} [{verdict['key']}]"


ORIGINAL = "Original instructions of the change set that failed"


def original_instructions(text):
    text = text or ""
    return text.split(f"#### {ORIGINAL}", 1)[1].split("\n#### ", 1)[0].strip() if f"#### {ORIGINAL}" in text else text.strip()


def request_text(doc, verdict, run_url="", original=""):
    ev = verdict["event"]
    happened = validate_bug.scrub(f"{ev['summary']}" + (f"\n\nEvidence: {ev['evidence']}" if ev.get("evidence") else "")) + (f"\n\nRun: {run_url}" if run_url else "")
    lines = ["#### What happened", "", happened, "", "#### How it was found", "", doc["how_found"], "", "#### Root cause", "", doc["root_cause"], "",
             "#### What it would take to resolve", "", *[f"- {x}" for x in doc["what_it_takes"]], "",
             "#### Requirements", "", *[f"{i}. {r}" for i, r in enumerate(doc["requirements"], 1)], "",
             "#### Target", "", TARGET_TEXT.get(verdict.get("target"), TARGET_TEXT["managed_app"]), "",
             *(["#### Cause", "", str(verdict["cause"]), ""] if verdict.get("target") == "factory" and verdict.get("cause") else []),
             "#### Failure and solution log", "", "_Comments on this issue record each failure and the solution._"]
    if original:
        lines += ["", f"#### {ORIGINAL}", "", original_instructions(original)]
    return "\n".join(lines)


def intake_body(app, doc, verdict, run_url="", cap=None, original="", fix_marker=""):
    return marker(verdict["key"]) + "\n" + (fix_marker + "\n" if fix_marker else "") + "\n" + render_form.form_body(app, request_text(doc, verdict, run_url, original), cap)


def factory_body(doc, verdict, run_url=""):
    return request_text(doc, verdict, run_url) + "\n\n" + marker(verdict["key"]) + "\n"
