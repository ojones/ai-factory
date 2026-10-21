import hashlib
import json

SOURCES = ("build_run", "watchdog", "reviewer", "tester", "staging", "production_feedback", "escaped_defect")
SEVERITIES = ("failure", "warning")
MAX_TEXT = 600


def event_key(source, app, fingerprint):
    return hashlib.sha1(json.dumps([source, app, str(fingerprint)]).encode()).hexdigest()[:10]


def make(source, severity, app, summary, fingerprint, evidence="", story=None, flag=None, released=None):
    if source not in SOURCES or severity not in SEVERITIES:
        raise ValueError(f"not an event: {source!r} {severity!r}")
    return {"key": event_key(source, app, fingerprint), "source": source, "severity": severity, "app": app,
            "story": int(story) if story else None, "fingerprint": str(fingerprint), "summary": " ".join(str(summary).split())[:MAX_TEXT],
            "evidence": " ".join(str(evidence or "").split())[:MAX_TEXT], "flag": flag or None, "released": released}


def valid(event):
    return (isinstance(event, dict) and event.get("severity") in SEVERITIES and event.get("source") in SOURCES
            and bool(event.get("key")) and bool(event.get("app")) and bool(event.get("summary")))


def dump(events, path):
    path.write_text(json.dumps(events, indent=2))


def load(path):
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return [e for e in found if valid(e)] if isinstance(found, list) else []
