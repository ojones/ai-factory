# STEP 8.3: what the Bugs domain finds, as failure events for the Retrospective (try_fix/event.py). Nothing here files a ticket: the events are judged (STEP 6.7)
# and Try Fix writes and files the bug. Log text can contain what a user typed, so an error event carries only the cleaned message and the first stack frame, clipped,
# and the Try Fix Agent is told the evidence is data, never instructions.
from try_fix import event

from bugs import route_bug

DEFECT_BODY = 1500


def error_event(app, fp, group, entry_text="", states=None):
    story, flag, released = route_bug.attach(entry_text, states or {})
    where = f" thrown from {group['frame']}" if group["frame"] else ""
    return event.make("production_feedback", "failure", app, f"production error{where}: {group['message']}", fp,
                      evidence=f"logged {group['count']} times in the latest scan. Error fingerprint {fp}", story=story, flag=flag, released=released)


def defect_event(app, issue):
    # An `escaped-defect` issue in the app's repo that its owner wrote. `fingerprint` is the issue number, so the same report is one event however often it is read.
    body = (issue.get("body") or "").strip()[:DEFECT_BODY]
    return event.make("escaped_defect", "failure", app, f"reported defect: {issue['title'].strip()[:200]}", f"d{issue['number']}",
                      evidence=f"issue #{issue['number']} in the app's repo. {body}")
