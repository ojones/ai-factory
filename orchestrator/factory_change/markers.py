import re

CHILD = "factory-change"
REPRODUCTION = "reproduction"
TIER = "tier"
PATHS = "paths"


def render(name, value):
    return f"<!-- {name}:{value} -->"


def read(body, name):
    found = re.search(rf"<!-- {re.escape(name)}:(.*?) -->", body or "")
    return found.group(1) if found else None
