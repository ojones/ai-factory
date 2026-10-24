import hashlib
import json
import re

from shared import github

from try_fix import render_bug

LABEL = "fix-request"
FACTORY_LABEL = "factory-fix-request"


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
    body = render_bug.factory_body(doc, verdict, run_url)
    out = github.run(["issue", "create", "--repo", repo, "--title", f"Fix request [{fp}] [{verdict['key']}]: {ev['summary'][:80]}", "--label",
                      f"{LABEL},{FACTORY_LABEL}" if target == "factory" else LABEL, "--body", body], token)
    m = re.search(r"https://\S+/issues/(\d+)", out.stdout or "")
    return {"target": target, "action": "fix_request", "number": int(m.group(1)) if m else None, "url": m.group(0) if m else ""}
