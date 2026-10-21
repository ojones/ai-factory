import json
import os

from shared import shell


def open_alert_issues(repo, label, env):
    out = shell.sh(["gh", "issue", "list", "--repo", repo, "--label", label, "--state", "open", "--json", "number,body"], env=env).stdout
    return json.loads(out or "[]")


def sync_alert_issue(repo, token, label, problems_found, body, title, resolved_comment, extra_labels=()):
    env = {**os.environ, "GH_TOKEN": token}
    open_issues = open_alert_issues(repo, label, env)
    if not problems_found:
        for i in open_issues:
            shell.sh(["gh", "issue", "close", str(i["number"]), "--repo", repo, "--comment", resolved_comment], env=env, check=False)
    elif not open_issues:
        labels = [flag for name in (label, *extra_labels) for flag in ("--label", name)]
        shell.sh(["gh", "issue", "create", "--repo", repo, *labels, "--title", title, "--body", body], env=env, check=False)
    elif (open_issues[0].get("body") or "").strip() != body.strip():
        shell.sh(["gh", "issue", "edit", str(open_issues[0]["number"]), "--repo", repo, "--body", body], env=env, check=False)
