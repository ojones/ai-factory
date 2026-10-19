# Test support: a fake `gh` for the issue calls ChildTickets makes (create, sub-issues, blockers, parent, comment, close), so tests exercise the
# real request shapes without GitHub. `fail` is a substring of "<METHOD> <path>"; a call that matches it answers with that HTTP status.
import json
from types import SimpleNamespace


class FakeIssues:
    def __init__(self, fail=None):
        self.issues, self.subs, self.blocked, self.calls, self.fail = {}, {}, {}, [], fail or {}
        self.next = 100

    def add(self, number=None, state="open", body="", labels=()):
        number = number or self.next
        self.next = max(self.next, number) + 1
        self.issues[number] = {"id": number * 1000, "number": number, "state": state, "body": body, "labels": [{"name": n} for n in labels]}
        return number

    def __call__(self, args, token, check=False):
        if args[0] != "api":
            self.calls.append(args)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        path = args[1].split("/", 3)[3]  # after repos/<owner>/<repo>/
        method = args[args.index("--method") + 1]
        fields = {}
        for flag, value in zip(args, args[1:]):
            if flag in ("-f", "-F"):
                k, v = value.split("=", 1)
                fields.setdefault(k, []).append(v)
        self.calls.append((method, path, fields))
        for needle, status in self.fail.items():
            if needle in f"{method} {path}":
                return SimpleNamespace(stdout="", stderr=f"HTTP {status}", returncode=1)
        return self.route(method, path, fields)

    def ok(self, doc):
        return SimpleNamespace(stdout=json.dumps(doc), stderr="", returncode=0)

    def route(self, method, path, fields):
        parts = path.split("?")[0].split("/")
        if parts == ["issues"] and method == "POST":
            n = self.add(body=fields["body"][0], labels=fields.get("labels[]", []))
            self.issues[n]["title"] = fields["title"][0]
            return self.ok(self.issues[n])
        n = int(parts[1])
        if len(parts) == 2:
            if method == "PATCH":
                self.issues[n]["state"] = fields["state"][0]
            return self.ok(self.issues[n])
        if parts[2] == "sub_issue" and method == "DELETE":
            self.subs[n] = [c for c in self.subs.get(n, []) if self.issues[c]["id"] != int(fields["sub_issue_id"][0])]
            return self.ok(self.issues[n])
        if parts[2] == "comments":
            return self.ok({})
        if parts[2] == "sub_issues" and method == "POST":
            child = next(i for i in self.issues.values() if str(i["id"]) == fields["sub_issue_id"][0])
            self.subs.setdefault(n, []).append(child["number"])
            return self.ok(self.issues[n])
        if parts[2] == "sub_issues":
            return self.ok([self.issues[c] for c in self.subs.get(n, [])])
        if parts[2] == "parent":
            parent = next((p for p, kids in self.subs.items() if n in kids), None)
            if parent is None:
                return SimpleNamespace(stdout='{"message":"No parent issue found"}', stderr="gh: No parent issue found (HTTP 404)", returncode=1)
            return self.ok(self.issues[parent])
        if parts[2] == "dependencies" and method == "POST":
            blocker = next(i for i in self.issues.values() if str(i["id"]) == fields["issue_id"][0])
            self.blocked.setdefault(n, []).append(blocker["number"])
            return self.ok(self.issues[n])
        if parts[2] == "dependencies":
            return self.ok([self.issues[b] for b in self.blocked.get(n, [])])
        raise AssertionError(f"unexpected call {method} {path}")
