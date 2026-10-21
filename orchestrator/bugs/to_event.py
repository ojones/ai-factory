from try_fix import event

from bugs import route_bug

DEFECT_BODY = 1500


def error_event(app, fp, group, entry_text="", states=None):
    story, flag, released = route_bug.attach(entry_text, states or {})
    where = f" thrown from {group['frame']}" if group["frame"] else ""
    return event.make("production_feedback", "failure", app, f"production error{where}: {group['message']}", fp,
                      evidence=f"logged {group['count']} times in the latest scan. Error fingerprint {fp}", story=story, flag=flag, released=released)


def defect_event(app, issue):
    body = (issue.get("body") or "").strip()[:DEFECT_BODY]
    return event.make("escaped_defect", "failure", app, f"reported defect: {issue['title'].strip()[:200]}", f"d{issue['number']}",
                      evidence=f"issue #{issue['number']} in the app's repo. {body}")
