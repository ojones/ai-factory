import hashlib
import json
import re

from shared import github

from try_fix import failure_text, render_bug

LABEL = "fix-request"
FACTORY_LABEL = "factory-fix-request"
FAILED_RE = re.compile(r"<!-- failed-child:(\d+) -->")


def failed_child_marker(number):
    return f"<!-- failed-child:{int(number)} -->"


def read_failed_child(text):
    m = FAILED_RE.search(text or "")
    return int(m.group(1)) if m else None


def fingerprint(app, child, target):
    return hashlib.sha1(f"{app}|{child}|{target}".encode()).hexdigest()[:8]


def file_bug_request(repo, token, verdict, doc, run_url, target):
    ev = verdict["event"]
    story = ev.get("story")
    fp = fingerprint(ev["app"], story or verdict["key"], target)
    for name, color, desc in ((LABEL, "d93f0b", "What has to be fixed after a Build Run ended badly"), (FACTORY_LABEL, "5319e7", "A fix request for the Factory itself")):
        github.ensure_label(repo, name, token, color, desc)
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--search", f"{fp} in:title", "--json", "number,title,url"], token).stdout or "[]")
    again = next((i for i in found if fp in i["title"]), None)
    if again:
        github.run(["issue", "comment", str(again["number"]), "--repo", repo, "--body", f"**Failed again** ({ev['source']}): {ev['summary']}\n{run_url}"], token)
        return {"target": target, "action": "fix_request", "number": again["number"], "url": again["url"]}
    body = render_bug.factory_body(doc, verdict, run_url) + ("\n" + failed_child_marker(story) if story else "")
    out = github.run(["issue", "create", "--repo", repo, "--title", f"Fix request [{fp}] [{verdict['key']}]: {ev['summary'][:80]}", "--label",
                      f"{LABEL},{FACTORY_LABEL}" if target == "factory" else LABEL, "--body", body], token)
    m = re.search(r"https://\S+/issues/(\d+)", out.stdout or "")
    return {"target": target, "action": "fix_request", "number": int(m.group(1)) if m else None, "url": m.group(0) if m else ""}


def file_request(repo, token, facts, result, rollback, target, category):
    app, number = facts.get("app"), facts.get("issue_number")
    fp = fingerprint(app, number, target)
    for name, color, desc in ((LABEL, "d93f0b", "What has to be fixed after a Build Run ended badly"), (FACTORY_LABEL, "5319e7", "A fix request for the Factory itself")):
        github.ensure_label(repo, name, token, color, desc)
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--search", f"{fp} in:title",
                                   "--json", "number,title,url"], token).stdout or "[]")
    again = next((i for i in found if fp in i["title"]), None)
    if again:
        github.run(["issue", "comment", str(again["number"]), "--repo", repo, "--body",
                    f"**Failed again** ({facts.get('outcome')}): {failure_text.clip(facts.get('message'), 300)}\n{facts.get('run_url')}\n\n{failure_text.rollback_line(rollback)}"], token)
        return {"action": "fix_request", "url": again["url"]}
    intake_url = f"https://github.com/{repo}/issues/{number}"
    labels = f"{LABEL},{FACTORY_LABEL}" if target == "factory" else LABEL
    body = failure_text.render(facts, result, rollback, target, intake_url) + "\n" + failed_child_marker(number)
    out = github.run(["issue", "create", "--repo", repo, "--title", f"Fix request [{fp}]: {category or 'unknown cause'} in {app}'s run for #{number}",
                      "--label", labels, "--body", body], token)
    m = re.search(r"https://\S+/issues/(\d+)", out.stdout or "")
    return {"action": "fix_request", "url": m.group(0) if m else ""}
