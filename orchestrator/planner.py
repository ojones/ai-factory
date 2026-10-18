#!/usr/bin/env python3
# Plan validation for the planner role (agents/prompts/planner.md).
#
# The planner Agent turns a larger Intake into a plan: requirements, the questions only a person can answer, and
# an ordered set of change sets, each one Build Run's work with its own acceptance criteria and flag. This module
# is the deterministic gate between that plan and any coding: nothing is dispatched from a plan that fails it, and
# a plan with an unanswered blocking question ends in a needs-human Issue instead of a guess.
#
# The plan format (JSON):
#
#   {"requirements": [{"id": "REQ-1", "text": "..."}],
#    "assumptions": ["..."],
#    "open_questions": [{"id": "Q-1", "text": "...", "blocking": true}],
#    "change_sets": [{"id": "CS-1", "title": "...", "requirements": ["REQ-1"], "depends_on": [],
#                     "criteria": ["AC-1: ..."], "verification": ["..."], "flag": "slug-or-null",
#                     "internal_only": false, "out_of_scope": ["..."]}]}
#
# Used by the Build Run for an Update Intake (`BuildRun.plan_change`): one change set becomes that run's task; several
# are filed as child Update Intake issues by `update_intake.file_children`, each its own Build Run, in this order.
#
# Usage: planner.py validate <plan.json> [first|update]     (exit 0 valid, 1 invalid, 2 needs a person)
import json
import re
import sys

import triage

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# A change set that exists only to add tests. Every change set includes its own tests, so this one has no outcome of its own.
# A change set that retires or removes a flag. Its flag must be null: the feature is already live, so a new flag would
# switch it off. (A run that invented `retire-delete-flag` for this turned a live DELETE endpoint dark.)
RETIRES_FLAG_RE = re.compile(r"\b(retire|retiring|remove|removing|delete|deleting|drop|dropping|clean ?up|get rid of)\b[^.]{0,60}\b(feature[- ]?)?flags?\b", re.I)
TESTS_ONLY_RE = re.compile(r"^\s*(add|write|create|update|improve|expand|implement)\b[^.]*\b(unit |integration |comprehensive |more |additional |extra )*(tests?|test coverage|test suite)(?![\w-])", re.I)
# A change set that bumps dependencies is a different kind of work from retiring a flag; they ship and fail separately.
DEPENDENCY_WORK_RE = re.compile(r"\b(bump|upgrad\w*|updat\w*|dependabot)\b[^.]{0,40}\b(dependenc\w*|packages?|npm|base image)\b", re.I)
# An HTTP route or a screen element in the criteria: something a user or a client can reach.
USER_REACHABLE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/|\bendpoints?\b|\broutes?\b|\bbuttons?\b|\bscreens?\b|\bpage\b", re.I)
MAX_CHANGE_SETS = 8


def _ids(items, key="id"):
    return [i.get(key) for i in items if isinstance(i, dict)]


def secret_problems(secrets):
    # Problems with a plan's `secrets` list: [{name, purpose, read_by}], one entry per service secret the build needs.
    if secrets in (None, []):
        return []
    if not isinstance(secrets, list):
        return ["`secrets` must be a list"]
    problems, names = [], []
    for x in secrets:
        if not isinstance(x, dict):
            problems.append("a secret is not an object")
            continue
        bad = triage.secret_name_problem(x.get("name"))
        if bad:
            problems.append(bad)
        if not str(x.get("purpose", "")).strip():
            problems.append(f"secret {x.get('name')} has no purpose (what it is for, in one sentence)")
        names.append(x.get("name"))
    if len(set(names)) != len(names):
        problems.append("secret names are not unique")
    return problems


def validate_plan(plan, build_kind="update", max_change_sets=MAX_CHANGE_SETS, reuse_flags=()):
    # (problems, questions). `problems` are reasons the plan cannot be used and must be redone; `questions` are
    # the blocking open questions a person has to answer first. A plan is ready only when both are empty.
    problems, questions = [], []
    if not isinstance(plan, dict):
        return ["the plan is not a JSON object"], []
    if isinstance(plan.get("feasibility"), dict) and plan["feasibility"].get("status") == "blocked":
        if not plan["feasibility"].get("reasons"):
            return ["a blocked request needs `reasons`: one plain sentence each, naming what in the request needs it"], []
        return [], []  # a refusal has no change sets to check

    reqs = plan.get("requirements")
    sets = plan.get("change_sets")
    if not isinstance(reqs, list) or not reqs:
        problems.append("no requirements listed")
        reqs = []
    if not isinstance(sets, list) or not sets:
        problems.append("no change sets listed")
        sets = []
    if len(sets) > max_change_sets:
        problems.append(f"{len(sets)} change sets is more than the limit of {max_change_sets}: split the request into separate Intakes")

    req_ids = _ids(reqs)
    for rid in req_ids:
        if not isinstance(rid, str) or not rid.strip():
            problems.append("a requirement has no id")
    if len(set(req_ids)) != len(req_ids):
        problems.append("requirement ids are not unique")
    for r in reqs:
        if isinstance(r, dict) and not str(r.get("text", "")).strip():
            problems.append(f"requirement {r.get('id')} has no text")

    ids = _ids(sets)
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i.strip() for i in ids):
        problems.append("change set ids are missing or not unique")
    flags = []
    covered = set()
    for cs in sets:
        if not isinstance(cs, dict):
            problems.append("a change set is not an object")
            continue
        name = cs.get("id") or "(no id)"
        if not str(cs.get("title", "")).strip():
            problems.append(f"{name} has no title")
        elif TESTS_ONLY_RE.match(str(cs["title"])):
            problems.append(f"{name} ({cs['title']!r}) is only tests: every change set includes its own tests, so fold them into the change set they test")
        criteria = cs.get("criteria")
        if not isinstance(criteria, list) or not [c for c in criteria if str(c).strip()]:
            problems.append(f"{name} has no acceptance criteria")
        if not cs.get("verification"):
            problems.append(f"{name} says nothing about how it will be verified")
        links = cs.get("requirements")
        if not isinstance(links, list) or not links:
            problems.append(f"{name} is not linked to any requirement")
        else:
            for link in links:
                if link not in req_ids:
                    problems.append(f"{name} refers to unknown requirement {link}")
                covered.add(link)
        for dep in cs.get("depends_on") or []:
            if dep not in ids:
                problems.append(f"{name} depends on unknown change set {dep}")
            if dep == cs.get("id"):
                problems.append(f"{name} depends on itself")
        flag = cs.get("flag")
        if flag is not None and RETIRES_FLAG_RE.search(str(cs.get("title", ""))):
            problems.append(f"{name} retires or removes a flag but is given the new flag {flag!r}: users see no difference, so set flag to null and internal_only to true")
        title = str(cs.get("title", ""))
        if RETIRES_FLAG_RE.search(title) and DEPENDENCY_WORK_RE.search(title):
            problems.append(f"{name} bundles a dependency update with retiring a flag: they ship and fail separately, so make them two change sets")
        if (cs.get("internal_only") and flag is None and not RETIRES_FLAG_RE.search(title)
                and USER_REACHABLE_RE.search(" ".join(str(c) for c in cs.get("criteria") or []))):
            problems.append(f"{name} is marked internal_only but its criteria name an endpoint, route or screen a user can reach: "
                            "a change to those is user-visible, so give it its own flag (describing it as tooling does not make it internal)")
        if flag is not None:
            if not isinstance(flag, str) or not SLUG_RE.fullmatch(flag):
                problems.append(f"{name} has an invalid flag slug {flag!r}")
            else:
                flags.append(flag)
        elif build_kind == "update" and not cs.get("internal_only"):
            problems.append(f"{name} is an update with a user-visible effect but no flag (set `flag`, or `internal_only: true` if users cannot see it)")
    if len(set(flags)) != len(flags):
        problems.append("two change sets share a flag: each change set has its own, so one can be switched off alone")
    if reuse_flags and len(sets) == 1 and flags and flags[0] not in reuse_flags:
        problems.append(f"this story is a retry and keeps its flag: use exactly {', '.join(repr(f) for f in reuse_flags)} for the change set, not {flags[0]!r}")

    for rid in req_ids:
        if rid not in covered:
            problems.append(f"requirement {rid} is not covered by any change set")

    order = topological_order(sets)
    if order is None:
        problems.append("the change sets' dependencies contain a cycle")

    problems += secret_problems(plan.get("secrets"))
    for q in plan.get("open_questions") or []:
        if isinstance(q, dict) and q.get("blocking"):
            questions.append(f"{q.get('id', '?')}: {q.get('text', '')}")
    return problems, questions


def topological_order(change_sets):
    # Change set ids in an order that respects `depends_on` (ties keep the listed order), or None if there is a cycle.
    sets = [cs for cs in change_sets if isinstance(cs, dict) and cs.get("id")]
    deps = {cs["id"]: [d for d in cs.get("depends_on") or [] if d in {c["id"] for c in sets}] for cs in sets}
    order, done = [], set()
    while len(order) < len(sets):
        ready = [cs["id"] for cs in sets if cs["id"] not in done and all(d in done for d in deps[cs["id"]])]
        if not ready:
            return None
        order.append(ready[0])
        done.add(ready[0])
    return order


def main(argv):
    if len(argv) < 3 or argv[1] != "validate":
        print("Usage: planner.py validate <plan.json> [first|update]     (exit 0 valid, 1 invalid, 2 needs a person)", file=sys.stderr)
        return 2
    with open(argv[2]) as f:
        plan = json.load(f)
    kind = "first build" if len(argv) > 3 and argv[3] == "first" else "update"
    problems, questions = validate_plan(plan, kind)
    for p in problems:
        print(f"INVALID: {p}")
    for q in questions:
        print(f"NEEDS A PERSON: {q}")
    if not problems and not questions:
        print("plan is valid; order:", " -> ".join(topological_order(plan["change_sets"])))
    return 1 if problems else (2 if questions else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
