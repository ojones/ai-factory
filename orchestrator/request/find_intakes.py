import json

from shared import github


def intakes_with(repo, token, app, label, state="open"):
    out = github.run(["issue", "list", "--repo", repo, "--label", f"{label},app:{app}", "--state", state, "--limit", "100",
                      "--json", "number,title,createdAt"], token).stdout
    return json.loads(out or "[]")
