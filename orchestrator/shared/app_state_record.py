# The format of the App State record, which Maintenance, Flag Lifecycle, Bugs and the Build Run all read: each issue body carries its data as
# JSON in an HTML comment, so a rewrite never has to parse the tables. The App State issue (label `factory-state`) lives in each Managed App's
# repo; the registry issue (label `factory-registry`) in ai-factory has one row per Managed App.
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
    # "--" inside an HTML comment could end it early; as a JSON escape it survives a round trip unchanged.
    return "<!-- factory-data:" + json.dumps(data, separators=(",", ":")).replace("--", "\\u002d\\u002d") + " -->"


def managed_apps(repo, token):
    out = github.run(["issue", "list", "--repo", repo, "--label", REGISTRY_LABEL, "--state", "open", "--json", "body"], token).stdout
    found = json.loads(out or "[]")
    return sorted(load(found[0]["body"]).get("apps", {})) if found else []
