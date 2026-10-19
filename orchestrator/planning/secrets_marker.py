# The hidden marker that records which secrets a request declared, and the reader that finds them again on any later start.
import json
import re

from shared import child_tickets

SECRETS_RE = re.compile(r"<!-- factory-secrets:(.*?) -->", re.S)


def secrets_marker(needed):
    # The hidden marker that records which secrets a request declared (names and purposes, never values), so every later start checks them
    # before any Agent is paid for, whichever path it takes.
    return "<!-- factory-secrets:" + json.dumps([{"name": x["name"], "purpose": x.get("purpose", "")} for x in needed], separators=(",", ":")) + " -->"


def declared_secrets(issue):
    # The secrets recorded for this Intake: in a hidden marker in any comment, or in a child issue's plan metadata. [{name, purpose}].
    found = {}
    sources = [c.get("body", "") for c in issue.get("comments") or []]
    for text in sources:
        m = SECRETS_RE.search(text or "")
        try:
            items = json.loads(m.group(1)) if m else []
        except ValueError:
            items = []
        for x in items if isinstance(items, list) else []:
            if isinstance(x, dict) and isinstance(x.get("name"), str):
                found[x["name"]] = {"name": x["name"], "purpose": str(x.get("purpose", ""))}
    for x in child_tickets.read_marker(issue.get("body")).get("secrets") or []:
        if isinstance(x, dict) and isinstance(x.get("name"), str):
            found[x["name"]] = {"name": x["name"], "purpose": str(x.get("purpose", ""))}
    return list(found.values())
