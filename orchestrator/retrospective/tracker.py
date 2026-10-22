import hashlib
import json
import os
import re

from shared.shell import sh

LABEL = "factory-learning"


STOP_WORDS = {"the", "a", "an", "is", "are", "was", "to", "of", "in", "on", "for", "and", "not", "no", "it", "this"}


def normalize(summary):
    words = [w for w in re.findall(r"[a-z0-9]+", summary.lower()) if w not in STOP_WORDS]
    return " ".join(words[:6])


def pick_existing(issues, title):
    open_n = next((i["number"] for i in issues if i["title"] == title and i.get("state", "OPEN").upper() == "OPEN"), None)
    closed_n = next((i["number"] for i in issues if i["title"] == title and i.get("state", "").upper() == "CLOSED"), None)
    return open_n, closed_n


def gh(args, token, check=False):
    return sh(["gh", *args], env={**os.environ, "GH_TOKEN": token}, check=check)


def minor_title(summary):
    return f"Minor finding [{hashlib.sha1(normalize(summary).encode()).hexdigest()[:8]}] {summary[:60]}"


def find_open_issue(repo, token, title, label=None):
    args = ["issue", "list", "--repo", repo, "--state", "open", "--search", f"{title[:80]} in:title", "--json", "number,title"]
    out = gh(args + (["--label", label] if label else []), token).stdout
    return next((i["number"] for i in json.loads(out or "[]") if i["title"] == title), None)


TITLE_NOISE = re.compile(r"\[[^\]]*\]|^\s*(improvement|suggestion|minor finding|lesson|bug)\b:?", re.I)


SIMILAR = 0.6


def content_words(text):
    words = re.findall(r"[a-z0-9]+", TITLE_NOISE.sub(" ", str(text).lower()))
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if len(w) > 2 and w not in STOP_WORDS}


def similar_open_issue(repo, token, summary, label=None, threshold=SIMILAR):
    wanted = content_words(str(summary)[:60])
    if not wanted:
        return None
    out = gh(["issue", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,title"]
             + (["--label", label] if label else []), token).stdout
    best, found = 0.0, None
    for issue in json.loads(out or "[]"):
        have = content_words(issue["title"])
        score = len(wanted & have) / len(wanted | have) if have else 0.0
        if score > best:
            best, found = score, issue["number"]
    return found if best >= threshold else None


SEEN_RE = re.compile(r"<!-- seen:(\{.*?\}) -->", re.S)


RECURRING_LABEL = "recurring"


def sightings(body):
    m = SEEN_RE.search(body or "")
    try:
        return dict(json.loads(m.group(1))) if m else {}
    except ValueError:
        return {}


def with_sighting(body, run_url, app):
    seen = sightings(body)
    seen[run_url] = app
    marker = f"<!-- seen:{json.dumps(seen, sort_keys=True)} -->"
    body = SEEN_RE.sub(marker, body, count=1) if SEEN_RE.search(body or "") else (body or "").rstrip() + "\n\n" + marker
    return body, len(seen), len(set(seen.values()))


def note_sighting(repo, token, number, facts, promote_after):
    out = gh(["issue", "view", str(number), "--repo", repo, "--json", "body"], token, check=True).stdout
    body, runs, _ = with_sighting((json.loads(out or "{}")).get("body") or "", facts["run_url"], facts["app"])
    gh(["issue", "edit", str(number), "--repo", repo, "--body", body] + (["--add-label", RECURRING_LABEL] if runs >= max(promote_after, 2) else []), token)
    return runs


def ready_for_fix(runs, promote_after, severe=False):
    return severe or promote_after <= 1 or runs >= promote_after


def already_proposed(repo, token, number):
    out = gh(["issue", "view", str(number), "--repo", repo, "--json", "comments"], token).stdout
    return "**PR**: http" in out
