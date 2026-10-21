import hashlib
import json
import os
import re

from shared.shell import sh

CLIP = 240
NOISE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b|\d+", re.I)
FRAME = re.compile(r"\(?((?:/|[A-Za-z]:)?[^\s()]*?[\w.-]+\.(?:ts|js|mjs|cjs|tsx|jsx)):\d+(?::\d+)?\)?")


def parse_events(log_text):
    out = []
    for line in (log_text or "").splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            entry = json.loads(line[start:])
        except ValueError:
            continue
        if isinstance(entry, dict) and str(entry.get("level", "")).lower() in ("error", "fatal"):
            out.append(entry)
    return out


def first_frame(entry):
    for key in ("stack", "err", "error"):
        text = entry.get(key)
        text = text.get("stack") if isinstance(text, dict) else text
        if isinstance(text, str):
            for m in FRAME.finditer(text):
                path = m.group(1)
                if "node_modules" not in path and not path.startswith("node:"):
                    return path.split("/dist/")[-1].split("/src/")[-1]
    return ""


def clean_message(entry):
    msg = str(entry.get("message") or entry.get("msg") or "error")
    err = entry.get("err") or entry.get("error")
    err = err.get("message") if isinstance(err, dict) else err
    if isinstance(err, str) and err and err not in msg:
        msg = f"{msg}: {err}"
    return re.sub(r"\s+", " ", NOISE.sub("N", msg)).strip()[:CLIP]


def fingerprint(entry):
    key = clean_message(entry) + "|" + first_frame(entry)
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def group(events):
    out = {}
    for e in events:
        fp = fingerprint(e)
        g = out.setdefault(fp, {"count": 0, "message": clean_message(e), "frame": first_frame(e), "sample": json.dumps(e)[:2000]})
        g["count"] += 1
    return out


def app_logs(app):
    p = sh(["flyctl", "logs", "--no-tail", "--app", app], env={**os.environ}, check=False, timeout=120)
    return p.stdout or ""
