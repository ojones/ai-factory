import json

from shared import github

DEFECT_LABEL = "escaped-defect"


def owner_defects(repo, pat, app):
    owner = repo.split("/")[0]
    out = github.run(["issue", "list", "--repo", f"{owner}/{app}", "--label", DEFECT_LABEL, "--state", "open", "--json", "number,title,body,author"], pat).stdout
    return [i for i in json.loads(out or "[]") if (i.get("author") or {}).get("login") == owner]


def tell_owner(repo, pat, app, issue_number, ticket):
    owner = repo.split("/")[0]
    github.run(["issue", "comment", str(issue_number), "--repo", f"{owner}/{app}", "--body", f"Filed as {repo}#{ticket}; the Factory is working on it."], pat)
