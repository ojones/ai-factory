import json
from types import SimpleNamespace


class FakeIssues:
    def __init__(self, fail=None):
        self.issues, self.subs, self.blocked, self.calls, self.fail = {}, {}, {}, [], fail or {}
        self.comments = {}
        self.next = 100

    def add(self, number=None, state="open", body="", labels=()):
        number = number or self.next
        self.next = max(self.next, number) + 1
        self.issues[number] = {"id": number * 1000, "number": number, "state": state, "body": body, "labels": [{"name": n} for n in labels]}
        return number

    def __call__(self, args, token, check=False):
        if args[0] != "api":
            self.calls.append(args)
            if args[:2] == ["issue", "create"]:
                made = self.add(body=args[args.index("--body") + 1], labels=args[args.index("--label") + 1].split(",") if "--label" in args else [])
                self.issues[made]["title"] = args[args.index("--title") + 1]
                return SimpleNamespace(stdout=f"https://github.com/o/f/issues/{made}", stderr="", returncode=0)
            if args[:2] == ["issue", "list"]:
                term = args[args.index("--search") + 1].replace(" in:title", "") if "--search" in args else ""
                need = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
                found = [i for i in self.issues.values() if i["state"] == "open" and term in i.get("title", "") and set(need) <= {x["name"] for x in i["labels"]}]
                return self.ok([{"number": i["number"], "title": i.get("title", ""), "url": f"https://github.com/o/f/issues/{i['number']}"} for i in found])
            if args[:2] == ["issue", "comment"] and int(args[2]) in self.issues:
                self.comments.setdefault(int(args[2]), []).append(args[args.index("--body") + 1])
            if args[:2] == ["issue", "view"] and int(args[2]) in self.issues:
                issue = self.issues[int(args[2])]
                return self.ok({"number": issue["number"], "title": issue.get("title", ""), "body": issue["body"], "state": issue["state"], "labels": issue["labels"],
                                "comments": [{"body": b} for b in self.comments.get(issue["number"], [])]})
            if args[:2] == ["issue", "edit"] and int(args[2]) in self.issues:
                labels = self.issues[int(args[2])]["labels"]
                for flag, value in zip(args, args[1:]):
                    if flag == "--add-label" and value not in [x["name"] for x in labels]:
                        labels.append({"name": value})
                    if flag == "--remove-label":
                        labels[:] = [x for x in labels if x["name"] != value]
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        path = args[1].split("/", 3)[3]
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
