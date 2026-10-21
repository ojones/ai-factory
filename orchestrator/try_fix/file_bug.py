import json
import re

from request import intake_labels, read_form
from shared import child_tickets, github

from try_fix import factory_fix_request, needs_human, render_bug

BUG_LABEL = "bug"


def _json(proc):
    return json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}


def _issue(repo, number, token):
    doc = _json(github.run(["issue", "view", str(number), "--repo", repo, "--json", "title,body,state,labels,comments"], token))
    return {"title": doc.get("title") or "", "body": doc.get("body") or "", "state": str(doc.get("state") or "").upper(),
            "comments": [c.get("body") or "" for c in doc.get("comments") or []]}


def comment_once(repo, token, number, marker, body, issue=None):
    seen = (issue or _issue(repo, number, token))["comments"]
    if any(marker in c for c in seen):
        return False
    github.run(["issue", "comment", str(number), "--repo", repo, "--body", f"{body}\n{marker}"], token)
    return True


def open_bug(repo, token, key):
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--state", "open", "--search", f"{key} in:title", "--json", "number,title,url"], token).stdout or "[]")
    return next((i for i in found if key in i["title"]), None)


def create(repo, pat, title, body, labels):
    out = github.run(["issue", "create", "--repo", repo, "--title", title, "--label", ",".join(labels), "--body", body], pat).stdout
    m = re.search(r"/issues/(\d+)", out or "")
    return int(m.group(1)) if m else None


def failure_comment(verdict, doc, run_url):
    ev = verdict["event"]
    return (f"**Failure found** ({ev['severity']}, {ev['source']}): {ev['summary']}\n\n" + (f"{ev['evidence']}\n\n" if ev.get("evidence") else "")
            + (f"Run: {run_url}\n\n" if run_url else "") + f"Root cause: {doc['root_cause']}")


def file_bug(repo, token, pat, verdict, doc, facts=None, max_attempts=2):
    ev, target = verdict["event"], verdict["target"]
    run_url = (facts or {}).get("run_url", "")
    story = ev.get("story")
    again = open_bug(repo, token, verdict["key"])
    if again:
        github.run(["issue", "comment", str(again["number"]), "--repo", repo, "--body", f"**Seen again** ({ev['source']}): {ev['summary']}\n{run_url}"], token)
        return {"target": target, "action": "again", "number": again["number"], "url": again["url"]}
    failed = _issue(repo, story, token) if story else None
    marker = child_tickets.read_marker(failed["body"]) if failed else {}
    if target != "managed_app":
        got = factory_fix_request.file_bug_request(repo, token, verdict, doc, run_url, target)
        if failed and marker and failed["state"] == "OPEN" and ev["severity"] == "failure":
            needs_human.hold(repo, token, story, ("a fault in the Factory itself (" + str(verdict.get("cause")) + ") was found; the child starts again by itself when the fix is merged")
                             if target == "factory" else "no cause was named, or it was infrastructure")
        return got
    app = ev["app"]
    parent = child_tickets.parent_info(repo, story, token) if marker else None
    dark = bool(failed and marker and parent and failed["state"] == "OPEN" and ev.get("released") is not True)
    for name, color, desc in ((BUG_LABEL, "d73a4a", "Something a Managed App does wrong"), (intake_labels.UPDATE_APP_INTAKE, "1d76db", "A change request for an existing Managed App"),
                              (child_tickets.WAIT, "fbca04", "Waiting for an earlier change set of the same plan"), (intake_labels.app_label(app), "1d76db", f"Issues about the Managed App {app}")):
        github.ensure_label(repo, name, pat, color, desc)
    title, labels = render_bug.title(verdict, app), [BUG_LABEL, intake_labels.app_label(app)]
    if story:
        comment_once(repo, token, story, f"<!-- bug-comment:{verdict['key']} -->", failure_comment(verdict, doc, run_url), failed)
    if not dark:
        number = create(repo, pat, title, render_bug.intake_body(app, doc, verdict, run_url), labels + [intake_labels.UPDATE_APP_INTAKE])
        if story and number:
            comment_once(repo, token, story, f"<!-- bug-filed:{verdict['key']} -->",
                         f"A bug ticket was filed for this: #{number}. The flag was already released, so it is planned as a new change.")
        return {"target": target, "action": "bug_intake", "number": number, "url": f"https://github.com/{repo}/issues/{number}" if number else ""}
    attempt = int(marker.get("fix_attempt") or 0) + 1
    if attempt > max_attempts:
        needs_human.hold(repo, token, story, f"this story has used its {max_attempts} fix attempt(s) (`fix_attempts_max`); a person decides")
        return {"target": target, "action": "needs_human", "number": None, "url": ""}
    fix = child_tickets.render_fix_for(story, parent["number"], attempt)
    original = render_bug.original_instructions(read_form.form_section(failed["body"], "What should change?"))
    number = create(repo, pat, title, render_bug.intake_body(app, doc, verdict, run_url, original=original, fix_marker=fix), labels)
    if not number:
        needs_human.hold(repo, token, story, "the bug ticket for it could not be filed")
        return {"target": target, "action": "needs_human", "number": None, "url": ""}
    try:
        child_tickets.ChildTickets(repo, parent["number"], pat).block(story, number)
    except child_tickets.ChildTicketError:
        github.run(["issue", "close", str(number), "--repo", repo, "--comment", "Closed: the failed change set could not be made to wait for it, so no fix was filed."], pat)
        needs_human.hold(repo, token, story, "the bug ticket for it could not be linked to it")
        return {"target": target, "action": "needs_human", "number": None, "url": ""}
    github.run(["issue", "edit", str(story), "--repo", repo, "--add-label", child_tickets.WAIT, "--remove-label", needs_human.LABEL], token)
    github.run(["issue", "edit", str(number), "--repo", repo, "--add-label", intake_labels.UPDATE_APP_INTAKE], pat)
    comment_once(repo, token, story, f"<!-- bug-filed:{verdict['key']} -->",
                 f"**Fix first.** This change set is not started again as it was. Bug #{number} was filed and will be planned into one change set; "
                 "this one starts again after that closes.")
    return {"target": target, "action": "bug_intake", "number": number, "url": f"https://github.com/{repo}/issues/{number}"}
