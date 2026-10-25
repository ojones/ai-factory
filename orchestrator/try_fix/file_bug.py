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


def label_specs(app):
    return ((BUG_LABEL, "d73a4a", "Something a Managed App does wrong"), (intake_labels.UPDATE_APP_INTAKE, "1d76db", "A change request for an existing Managed App"),
            (child_tickets.WAIT, "fbca04", "Waiting for an earlier change set of the same plan"), (intake_labels.app_label(app), "1d76db", f"Issues about the Managed App {app}"))


class BugFiling:
    def __init__(self, repo, token, pat, verdict, doc, facts, max_attempts):
        self.repo, self.token, self.pat, self.verdict, self.doc, self.max_attempts = repo, token, pat, verdict, doc, max_attempts
        self.ev, self.target = verdict["event"], verdict["target"]
        self.run_url = (facts or {}).get("run_url", "")
        self.story = self.ev.get("story")

    def result(self, action, number=None, url=""):
        return {"target": self.target, "action": action, "number": number, "url": url}

    def issue_url(self, number):
        return f"https://github.com/{self.repo}/issues/{number}" if number else ""

    def hold(self, reason):
        needs_human.hold(self.repo, self.token, self.story, reason)

    def note_once(self, kind, text):
        comment_once(self.repo, self.token, self.story, f"<!-- {kind}:{self.verdict['key']} -->", text, self.failed)

    def seen_again(self, again):
        text = f"**Seen again** ({self.ev['source']}): {self.ev['summary']}\n{self.run_url}"
        github.run(["issue", "comment", str(again["number"]), "--repo", self.repo, "--body", text], self.token)
        return self.result("again", again["number"], again["url"])

    def story_is_open_child(self):
        return bool(self.failed and self.marker and self.failed["state"] == "OPEN")

    def for_factory(self):
        got = factory_fix_request.file_bug_request(self.repo, self.token, self.verdict, self.doc, self.run_url, self.target)
        if self.ev["source"] == "staging" and self.story_is_open_child():
            self.point_staging_at(got)
        elif self.story_is_open_child() and self.ev["severity"] == "failure":
            self.hold(self.factory_hold_reason())
        return got

    def point_staging_at(self, got):
        self.note_once("staging-fix", f"Staging cannot pass until the Factory is fixed: {got['url']}. Add `proceed-with-change` to this child again once that is closed.")

    def factory_hold_reason(self):
        if self.target != "factory":
            return "no cause was named, or it was infrastructure"
        return f"a fault in the Factory itself ({self.verdict.get('cause')}) was found and filed as a fix request in the Factory repo for a person to fix"

    def file_released(self, app, title, labels):
        number = create(self.repo, self.pat, title, render_bug.intake_body(app, self.doc, self.verdict, self.run_url), labels + [intake_labels.UPDATE_APP_INTAKE])
        if self.story and number:
            self.note_once("bug-filed", f"A bug ticket was filed for this: #{number}. The flag was already released, so it is planned as a new change.")
        return self.result("bug_intake", number, self.issue_url(number))

    def link_failed_child(self, number):
        try:
            child_tickets.ChildTickets(self.repo, self.parent["number"], self.pat).block(self.story, number)
        except child_tickets.ChildTicketError:
            github.run(["issue", "close", str(number), "--repo", self.repo, "--comment", "Closed: the failed change set could not be made to wait for it, so no fix was filed."], self.pat)
            self.hold("the bug ticket for it could not be linked to it")
            return False
        return True

    def file_fix_child(self, app, title, labels, attempt):
        fix = child_tickets.render_fix_for(self.story, self.parent["number"], attempt)
        original = render_bug.original_instructions(read_form.form_section(self.failed["body"], "What should change?"))
        return create(self.repo, self.pat, title, render_bug.intake_body(app, self.doc, self.verdict, self.run_url, original=original, fix_marker=fix), labels)

    def make_story_wait(self, number):
        github.run(["issue", "edit", str(self.story), "--repo", self.repo, "--add-label", child_tickets.WAIT, "--remove-label", needs_human.LABEL], self.token)
        github.run(["issue", "edit", str(number), "--repo", self.repo, "--add-label", intake_labels.UPDATE_APP_INTAKE], self.pat)

    def file_fix_first(self, app, title, labels):
        attempt = int(self.marker.get("fix_attempt") or 0) + 1
        if attempt > self.max_attempts:
            self.hold(f"this story has used its {self.max_attempts} fix attempt(s) (`fix_attempts_max`); a person decides")
            return self.result("needs_human")
        number = self.file_fix_child(app, title, labels, attempt)
        if not number:
            self.hold("the bug ticket for it could not be filed")
            return self.result("needs_human")
        if not self.link_failed_child(number):
            return self.result("needs_human")
        self.make_story_wait(number)
        self.note_once("bug-filed", f"**Fix first.** This change set is not started again as it was. Bug #{number} was filed and will be planned into one change set; this one starts again after that closes.")
        return self.result("bug_intake", number, self.issue_url(number))

    def for_app(self):
        app = self.ev["app"]
        self.parent = child_tickets.parent_info(self.repo, self.story, self.token) if self.marker else None
        dark = bool(self.story_is_open_child() and self.parent and self.ev.get("released") is not True)
        for name, color, desc in label_specs(app):
            github.ensure_label(self.repo, name, self.pat, color, desc)
        title, labels = render_bug.title(self.verdict, app), [BUG_LABEL, intake_labels.app_label(app)]
        if self.story:
            self.note_once("bug-comment", failure_comment(self.verdict, self.doc, self.run_url))
        return self.file_fix_first(app, title, labels) if dark else self.file_released(app, title, labels)

    def file(self):
        again = open_bug(self.repo, self.token, self.verdict["key"])
        if again:
            return self.seen_again(again)
        self.failed = _issue(self.repo, self.story, self.token) if self.story else None
        self.marker = child_tickets.read_marker(self.failed["body"]) if self.failed else {}
        return self.for_factory() if self.target != "managed_app" else self.for_app()


def file_bug(repo, token, pat, verdict, doc, facts=None, max_attempts=2):
    return BugFiling(repo, token, pat, verdict, doc, facts, max_attempts).file()
