import contextlib
import json
import re

from shared import github

FLAG_SLOT = "{{flag_slug}}"
WAIT = "waiting-on-plan"
META_RE = re.compile(r"<!-- factory-plan:(.*?) -->", re.S)
FIX_RE = re.compile(r"<!-- fix-for:(.*?) -->", re.S)


def read_marker(body):
    m = META_RE.search(body or "")
    if not m:
        return {}
    try:
        meta = json.loads(m.group(1))
        return meta if isinstance(meta, dict) else {}
    except ValueError:
        return {}


def render_marker(meta):
    return f"<!-- factory-plan:{json.dumps(meta, separators=(',', ':'))} -->"


def read_fix_for(body):
    m = FIX_RE.search(body or "")
    if not m:
        return {}
    try:
        meta = json.loads(m.group(1))
    except ValueError:
        return {}
    return meta if isinstance(meta, dict) and meta.get("fix_for") else {}


def render_fix_for(fix_for, origin_parent, attempt):
    meta = {"fix_for": int(fix_for), "origin_parent": int(origin_parent), "attempt": int(attempt)}
    return f"<!-- fix-for:{json.dumps(meta, separators=(',', ':'))} -->"


KINDS = ("staging", "update")


class ChildTicketError(RuntimeError):
    pass


def marker_for(cs, parent, kind="update", secrets=None, fix_for=None, fix_attempt=None):
    meta = {"parent": parent, "cs": cs["id"], "kind": kind, "flag": bool(cs.get("flag")), "internal_only": bool(cs.get("internal_only")),
            "size": cs.get("size"), "requirements": list(cs.get("requirements") or [])}
    if fix_for:
        meta["fix_for"] = int(fix_for)
    if fix_attempt:
        meta["fix_attempt"] = int(fix_attempt)
    if secrets:
        meta["secrets"] = [{"name": x["name"], "purpose": x.get("purpose", "")} for x in secrets]
    return meta


class ChildTickets:
    def __init__(self, repo, parent, token, run=None):
        self.repo, self.parent, self.token, self._run = repo, int(parent), token, run or github.run

    def _api(self, path, *fields, method="GET"):
        args = ["api", f"repos/{self.repo}/{path}", "--method", method]
        for f in fields:
            args += ["-F", f] if f.startswith(("sub_issue_id=", "issue_id=")) else ["-f", f]
        p = self._run(args, self.token)
        if p.returncode != 0:
            raise ChildTicketError(f"GitHub refused `{method} {path}`: {(p.stderr or p.stdout or '').strip()[:200]}")
        try:
            return json.loads(p.stdout) if (p.stdout or "").strip() else None
        except ValueError:
            raise ChildTicketError(f"GitHub answered `{method} {path}` with something that is not JSON")

    def children(self):
        out = self._api(f"issues/{self.parent}/sub_issues?per_page=100") or []
        return [{"number": c["number"], "id": c["id"], "state": c["state"].upper(), "labels": {label["name"] for label in c.get("labels") or []},
                 "marker": read_marker(c.get("body"))} for c in out]

    def file(self, title, body, labels):
        fields = [f"title={title}", f"body={body}"] + [f"labels[]={label}" for label in labels]
        made = self._api("issues", *fields, method="POST")
        if not isinstance(made, dict) or "id" not in made or "number" not in made:
            raise ChildTicketError("GitHub did not return the new issue")
        try:
            self._api(f"issues/{self.parent}/sub_issues", f"sub_issue_id={made['id']}", method="POST")
        except ChildTicketError:
            self.close(made["number"], "Closed: it could not be added under its parent, so the plan was not filed.")
            raise
        return made["number"]

    def block(self, number, blocker):
        blocking = self._api(f"issues/{blocker}")
        self._api(f"issues/{number}/dependencies/blocked_by", f"issue_id={blocking['id']}", method="POST")

    def blockers(self, number):
        return [{"number": b["number"], "state": b["state"].upper()} for b in self._api(f"issues/{number}/dependencies/blocked_by") or []]

    def is_ready(self, number):
        return self._api(f"issues/{number}")["state"].upper() == "OPEN" and all(b["state"] == "CLOSED" for b in self.blockers(number))

    def withdraw(self, number, comment):
        for path, fields, method in ((f"issues/{self.parent}/sub_issue", [f"sub_issue_id={self._api(f'issues/{number}')['id']}"], "DELETE"),):
            with contextlib.suppress(ChildTicketError):
                self._api(path, *fields, method=method)
        self.close(number, comment)

    def close(self, number, comment):
        for path, fields, method in ((f"issues/{number}/comments", [f"body={comment}"], "POST"), (f"issues/{number}", ["state=closed"], "PATCH")):
            with contextlib.suppress(ChildTicketError):
                self._api(path, *fields, method=method)


def parent_info(repo, number, token, run=None):
    p = (run or github.run)(["api", f"repos/{repo}/issues/{number}/parent", "--method", "GET"], token)
    if p.returncode == 0:
        doc = json.loads(p.stdout)
        return {"number": int(doc["number"]), "state": str(doc.get("state", "")).upper()}
    if "404" in (p.stderr or "") or "No parent issue" in (p.stdout or "") + (p.stderr or ""):
        return None
    raise ChildTicketError(f"GitHub refused the parent lookup for #{number}: {(p.stderr or '').strip()[:200]}")


def parent_of(repo, number, token, run=None):
    info = parent_info(repo, number, token, run)
    return info["number"] if info else None
