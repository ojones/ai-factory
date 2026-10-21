import re

from retrospective import tracker

MAX_MINORS = 5


def record_minors(repo, token, facts):
    tracker.gh(["label", "create", tracker.LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    recorded = []
    for m in facts["final_minor"][:MAX_MINORS]:
        title = tracker.minor_title(m["summary"])
        where = f"{m['file']}:{m['line']}" if m.get("file") else ""
        detail = f"{m['summary']}\n\nEvidence: {m['evidence']}\n{('Where: ' + where) if where else ''}\n"
        number = tracker.find_open_issue(repo, token, title, tracker.LABEL) or tracker.similar_open_issue(repo, token, m["summary"], tracker.LABEL)
        if number:
            tracker.gh(["issue", "comment", str(number), "--repo", repo, "--body", f"Seen again in `{facts['app']}`: {facts['run_url']}\n\n{m['summary']}\n{m['evidence']}"], token)
        else:
            out = tracker.gh(["issue", "create", "--repo", repo, "--label", tracker.LABEL, "--title", title, "--body",
                      detail + f"\nFirst seen in `{facts['app']}`: {facts['run_url']}"], token).stdout
            found = re.search(r"/issues/(\d+)", out)
            number = int(found.group(1)) if found else None
        if number:
            recorded.append((number, tracker.already_proposed(repo, token, number)))
    return recorded
