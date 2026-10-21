import json
import re

from shared import github

STATE_LABEL = "factory-state"
REGISTRY_LABEL = "factory-registry"
DATA_RE = re.compile(r"<!-- factory-data:(.*?) -->", re.S)


def load(body):
    m = DATA_RE.search(body or "")
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


def dump(data):
    return "<!-- factory-data:" + json.dumps(data, separators=(",", ":")).replace("--", "\\u002d\\u002d") + " -->"


def managed_apps(repo, token):
    out = github.run(["issue", "list", "--repo", repo, "--label", REGISTRY_LABEL, "--state", "open", "--json", "body"], token).stdout
    found = json.loads(out or "[]")
    return sorted(load(found[0]["body"]).get("apps", {})) if found else []
