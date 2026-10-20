# Finding and counting the issues the retrospective files in ai-factory: duplicates by fingerprint or similar words, how many distinct runs saw
# the same finding, and whether an issue already has a proposed PR.
import hashlib
import json
import os
import re

from shared.shell import sh

LABEL = "factory-learning"


STOP_WORDS = {"the", "a", "an", "is", "are", "was", "to", "of", "in", "on", "for", "and", "not", "no", "it", "this"}


def normalize(summary):
    # The first few meaningful words of a finding, so rewordings of one problem match.
    words = [w for w in re.findall(r"[a-z0-9]+", summary.lower()) if w not in STOP_WORDS]
    return " ".join(words[:6])


def pick_existing(issues, title):
    # (open issue number, closed issue number) among issues whose title matches exactly.
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


SIMILAR = 0.6  # share of the words two issue titles have in common for them to count as the same problem


def content_words(text):
    words = re.findall(r"[a-z0-9]+", TITLE_NOISE.sub(" ", str(text).lower()))
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if len(w) > 2 and w not in STOP_WORDS}  # "say" and "says" match


def similar_open_issue(repo, token, summary, label=None, threshold=SIMILAR):
    # The number of an open issue in `repo` that is about the same problem as `summary`, or None. Reworded titles still match (compared by
    # their content words, ignoring the `[fingerprint]` and the Improvement/Suggestion prefix), so a repeat adds context to the issue that
    # exists instead of opening a second one. Looks at the 100 most recent open issues.
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
    # {run url: app} recorded in an issue body's hidden `seen` marker.
    m = SEEN_RE.search(body or "")
    try:
        return dict(json.loads(m.group(1))) if m else {}
    except ValueError:
        return {}


def with_sighting(body, run_url, app):
    # The body with this run added to its hidden marker, and the counts: (body, distinct runs, distinct apps). Keyed by run URL, so a
    # retry of the same run, or the same run reported twice, is one sighting.
    seen = sightings(body)
    seen[run_url] = app
    marker = f"<!-- seen:{json.dumps(seen, sort_keys=True)} -->"
    body = SEEN_RE.sub(marker, body, count=1) if SEEN_RE.search(body or "") else (body or "").rstrip() + "\n\n" + marker
    return body, len(seen), len(set(seen.values()))


def note_sighting(repo, token, number, facts, promote_after):
    # Count this run against a `factory-learning` issue (hidden marker in its body; the label `recurring` once `promote_after` distinct
    # runs have seen it). Returns the number of distinct runs.
    out = gh(["issue", "view", str(number), "--repo", repo, "--json", "body"], token).stdout
    body, runs, _ = with_sighting((json.loads(out or "{}")).get("body") or "", facts["run_url"], facts["app"])
    gh(["issue", "edit", str(number), "--repo", repo, "--body", body] + (["--add-label", RECURRING_LABEL] if runs >= max(promote_after, 2) else []), token)
    return runs


def ready_for_fix(runs, promote_after, severe=False):
    # Whether an issue earns the Agent's analysis and fix PR: at once when it is severe or `promote_after` is 1 or less, otherwise once
    # that many distinct runs have seen it. One-off findings are still recorded and counted.
    return severe or promote_after <= 1 or runs >= promote_after


def already_proposed(repo, token, number):
    out = gh(["issue", "view", str(number), "--repo", repo, "--json", "comments"], token).stdout
    return "**PR**: http" in out
