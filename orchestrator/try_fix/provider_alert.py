# One alert for the whole Factory when the model provider has no balance: nothing a fix child or a learning PR does helps until someone tops up.
import json
import re

from shared import github

from try_fix.failure_text import rollback_line


def provider_alert_body(facts):
    return (f"## The model provider has no balance\n\nA Build Run for `{facts.get('app')}` stopped because the model provider refused "
            f"the request: the account has no balance (HTTP 402, \"You need positive balance to do inference\").\n\n"
            f"- Run: {facts.get('run_url')}\n- Request: #{facts.get('issue_number')}\n\n"
            "## What was done automatically\n\n" + rollback_line(facts.get("rollback")) + "\n\n"
            "## What to do\n\n1. Add balance in the provider's dashboard (or turn on auto top-up).\n"
            "2. For a child ticket that stopped, add `proceed-with-change` again (the Orchestrator removed it, so the label fires again). "
            "For an Intake that was not planned, remove its label and add it again.\n\n"
            "Every Build Run fails until this is done. Nothing was retried automatically, and no fix request or retrospective was started, "
            "because they would fail the same way.\n")


def file_provider_alert(repo, token, facts):
    # One open alert for the whole Factory: later blocked runs add a comment. Returns its URL.
    for name, color, desc in (("provider-blocked", "b60205", "The model provider refuses requests (no balance)"),
                              ("needs-human", "b60205", "The Orchestrator stopped and needs a person")):
        github.ensure_label(repo, name, token, color, desc)
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--label", "provider-blocked", "--state", "open", "--json", "number,url"], token).stdout or "[]")
    if found:
        github.run(["issue", "comment", str(found[0]["number"]), "--repo", repo, "--body",
            f"**Blocked again**: `{facts.get('app')}`, request #{facts.get('issue_number')}, {facts.get('run_url')}"], token)
        return found[0]["url"]
    out = github.run(["issue", "create", "--repo", repo, "--title", "Model provider has no balance: Build Runs are failing", "--label",
              "provider-blocked,needs-human", "--body", provider_alert_body(facts)], token)
    m = re.search(r"https://\S+/issues/\d+", out.stdout or "")
    return m.group(0) if m else ""
