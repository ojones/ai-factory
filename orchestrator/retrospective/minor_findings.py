# Minor findings still open at the end of a run become a suggestion issue in the Managed App's repo and a `factory-learning` issue in ai-factory.
import re

from retrospective import tracker

MAX_MINORS = 5  # per run, so one noisy review cannot flood the trackers


def record_minors(repo, token, app_repo, pat, facts):
    # Suggestion issues in the Managed App's repo; one factory-learning issue per distinct finding.
    # Returns [(factory issue number, already proposed)].
    tracker.gh(["label", "create", tracker.LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    recorded = []
    for m in facts["final_minor"][:MAX_MINORS]:
        title = tracker.minor_title(m["summary"])
        where = f"{m['file']}:{m['line']}" if m.get("file") else ""
        detail = f"{m['summary']}\n\nEvidence: {m['evidence']}\n{('Where: ' + where) if where else ''}\n"
        have = tracker.find_open_issue(app_repo, pat, "Suggestion: " + m["summary"][:70]) or tracker.similar_open_issue(app_repo, pat, m["summary"])
        if have:
            tracker.gh(["issue", "comment", str(have), "--repo", app_repo, "--body",
                f"More context, from the reviewer in `{facts['app']}`: {m['summary']}\n\nEvidence: {m['evidence']}\n{('Where: ' + where) if where else ''}\n{facts['run_url']}"], pat)
        else:
            tracker.gh(["issue", "create", "--repo", app_repo, "--title", "Suggestion: " + m["summary"][:70], "--body",
                detail + f"\nFound by the reviewer during the Build Run: {facts['run_url']}"], pat)
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
