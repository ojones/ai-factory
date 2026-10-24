import re

from planning import triage

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RETIRES_FLAG_RE = re.compile(r"\b(retire|retiring|remove|removing|delete|deleting|drop|dropping|clean ?up|get rid of)\b[^.]{0,60}\b(feature[- ]?)?flags?\b", re.I)
TESTS_ONLY_RE = re.compile(r"^\s*(add|write|create|update|improve|expand|implement)\b[^.]*\b(unit |integration |comprehensive |more |additional |extra )*(tests?|test coverage|test suite)(?![\w-])", re.I)
DEPENDENCY_WORK_RE = re.compile(r"\b(bump|upgrad\w*|updat\w*|dependabot)\b[^.]{0,40}\b(dependenc\w*|packages?|npm|base image)\b", re.I)
USER_REACHABLE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/|\bendpoints?\b|\broutes?\b|\bbuttons?\b|\bscreens?\b|\bpage\b", re.I)
MAX_CHANGE_SETS = 8
MAX_CRITERIA = 6
SIZES = ("S", "M")
KINDS = ("staging", "update")
CS_MENTION_RE = re.compile(r"\bCS-\d+\b")


def _ids(items, key="id"):
    return [i.get(key) for i in items if isinstance(i, dict)]


def secret_problems(secrets):
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


def listed(value):
    return value if isinstance(value, list) else []


def blocked_problems(plan):
    if plan["feasibility"].get("reasons"):
        return []
    return ["a blocked request needs `reasons`: one plain sentence each, naming what in the request needs it"]


def is_blocked(plan):
    return isinstance(plan.get("feasibility"), dict) and plan["feasibility"].get("status") == "blocked"


def size_limit_problems(reqs, sets, max_change_sets):
    problems = [] if reqs else ["no requirements listed"]
    problems += [] if sets else ["no change sets listed"]
    if len(sets) > max_change_sets:
        problems.append(f"{len(sets)} change sets is more than the limit of {max_change_sets}: split the request into separate Intakes")
    return problems


def requirement_problems(reqs):
    ids = _ids(reqs)
    problems = ["a requirement has no id" for rid in ids if not isinstance(rid, str) or not rid.strip()]
    if len(set(ids)) != len(ids):
        problems.append("requirement ids are not unique")
    return problems + [f"requirement {r.get('id')} has no text" for r in reqs if isinstance(r, dict) and not str(r.get("text", "")).strip()]


def change_set_id_problems(ids):
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i.strip() for i in ids):
        return ["change set ids are missing or not unique"]
    return []


def title_problems(name, cs):
    if not str(cs.get("title", "")).strip():
        return [f"{name} has no title"]
    if TESTS_ONLY_RE.match(str(cs["title"])):
        return [f"{name} ({cs['title']!r}) is only tests: every change set includes its own tests, so fold them into the change set they test"]
    return []


def criteria_problems(name, cs, max_criteria):
    criteria = cs.get("criteria")
    if not isinstance(criteria, list) or not [c for c in criteria if str(c).strip()]:
        return [f"{name} has no acceptance criteria"]
    if len(criteria) > max_criteria:
        return [f"{name} has {len(criteria)} acceptance criteria, more than {max_criteria}: it is more than one slice to release and revert together, so split it"]
    return []


def size_problems(name, cs):
    size = cs.get("size")
    if size == "L":
        return [f"{name} is size L: too big to release and revert as one change, so split it into S or M change sets"]
    return [] if size in SIZES else [f"{name} has no size (S or M)"]


def kind_problems(name, cs, build_kind):
    kind = cs.get("kind") or "update"
    if kind not in KINDS:
        return [f"{name} has an unknown kind {kind!r} (staging or update)"]
    if kind == "staging" and build_kind == "update":
        return [f"{name} is a staging change set, but the app already exists: staging is only for the first change set of a new app"]
    if kind == "staging" and cs.get("flag") is not None:
        return [f"{name} is the staging change set: it has no business logic and goes live on deploy, so its flag must be null"]
    return []


def mentioned_change_sets(cs):
    criteria = cs.get("criteria")
    texts = (cs.get("title"), *(criteria if isinstance(criteria, list) else []), *(cs.get("verification") or []))
    return sorted(set(CS_MENTION_RE.findall(" ".join(str(x) for x in texts))))


def mention_problems(name, cs):
    undeclared = [m for m in mentioned_change_sets(cs) if m != cs.get("id") and m not in (cs.get("depends_on") or [])]
    return [f"{name} mentions {other} but does not depend on it: a change set that only works with another's change (or flag) on has to say so in `depends_on`, or stand alone" for other in undeclared]


def verification_problems(name, cs):
    return [] if cs.get("verification") else [f"{name} says nothing about how it will be verified"]


def linked_requirements(cs):
    links = cs.get("requirements")
    return links if isinstance(links, list) else []


def link_problems(name, cs, req_ids):
    if (cs.get("kind") or "update") == "staging" and not cs.get("requirements"):
        return []
    if not linked_requirements(cs):
        return [f"{name} is not linked to any requirement"]
    return [f"{name} refers to unknown requirement {link}" for link in linked_requirements(cs) if link not in req_ids]


def dependency_problems(name, cs, ids):
    problems = []
    for dep in cs.get("depends_on") or []:
        problems += [f"{name} depends on unknown change set {dep}"] if dep not in ids else []
        problems += [f"{name} depends on itself"] if dep == cs.get("id") else []
    return problems


def flag_scope_problems(name, cs):
    title = str(cs.get("title", ""))
    problems = []
    if cs.get("flag") is not None and RETIRES_FLAG_RE.search(title):
        problems.append(f"{name} retires or removes a flag but is given the new flag {cs['flag']!r}: users see no difference, so set flag to null and internal_only to true")
    if RETIRES_FLAG_RE.search(title) and DEPENDENCY_WORK_RE.search(title):
        problems.append(f"{name} bundles a dependency update with retiring a flag: they ship and fail separately, so make them two change sets")
    return problems


def claims_internal_but_reachable(cs):
    criteria = " ".join(str(c) for c in cs.get("criteria") or [])
    retires = RETIRES_FLAG_RE.search(str(cs.get("title", "")))
    return bool(cs.get("internal_only") and cs.get("flag") is None and not retires and USER_REACHABLE_RE.search(criteria))


def flag_problems(name, cs, build_kind):
    flag = cs.get("flag")
    if claims_internal_but_reachable(cs):
        return [f"{name} is marked internal_only but its criteria name an endpoint, route or screen a user can reach: "
                "a change to those is user-visible, so give it its own flag (describing it as tooling does not make it internal)"]
    if flag is True:
        return []
    if flag is not None:
        return [] if flag_slug(cs) else [f"{name} has an invalid flag slug {flag!r}"]
    if build_kind == "update" and not cs.get("internal_only"):
        return [f"{name} is an update with a user-visible effect but no flag (set `flag`, or `internal_only: true` if users cannot see it)"]
    return []


def flag_slug(cs):
    flag = cs.get("flag")
    return flag if isinstance(flag, str) and SLUG_RE.fullmatch(flag) else None


def change_set_problems(cs, req_ids, ids, build_kind, max_criteria):
    if not isinstance(cs, dict):
        return ["a change set is not an object"]
    name = cs.get("id") or "(no id)"
    groups = (title_problems(name, cs), criteria_problems(name, cs, max_criteria), size_problems(name, cs), kind_problems(name, cs, build_kind),
              mention_problems(name, cs), verification_problems(name, cs), link_problems(name, cs, req_ids), dependency_problems(name, cs, ids),
              flag_scope_problems(name, cs), flag_problems(name, cs, build_kind))
    return [problem for group in groups for problem in group]


def shared_flag_problems(sets):
    flags = [flag_slug(cs) for cs in sets if isinstance(cs, dict) and flag_slug(cs)]
    if len(set(flags)) != len(flags):
        return ["two change sets share a flag: each change set has its own, so one can be switched off alone"]
    return []


def uncovered_problems(sets, req_ids):
    covered = {link for cs in sets if isinstance(cs, dict) for link in linked_requirements(cs)}
    return [f"requirement {rid} is not covered by any change set" for rid in req_ids if rid not in covered]


def staging_order_problems(order, sets):
    by_id = {cs["id"]: cs for cs in sets if isinstance(cs, dict) and cs.get("id")}
    staging = [i for i in order if (by_id[i].get("kind") or "update") == "staging"]
    if staging != order[:1]:
        return ["the first change set of a new app must be the only one of kind `staging` (repo, deploy, flag service and secrets verified, no business logic)"]
    if any(order[0] not in _ancestors(by_id, i) for i in order[1:]):
        return [f"every change set after the staging one ({order[0]}) must depend on it, directly or not"]
    return []


def order_problems(sets, build_kind):
    order = topological_order(sets)
    if order is None:
        return ["the change sets' dependencies contain a cycle"]
    return staging_order_problems(order, sets) if build_kind != "update" and sets else []


def blocking_questions(plan):
    asked = [q for q in plan.get("open_questions") or [] if isinstance(q, dict) and q.get("blocking")]
    return [f"{q.get('id', '?')}: {q.get('text', '')}" for q in asked]


def validate_plan(plan, build_kind="update", max_change_sets=MAX_CHANGE_SETS, max_criteria=MAX_CRITERIA):
    if not isinstance(plan, dict):
        return ["the plan is not a JSON object"], []
    if is_blocked(plan):
        return blocked_problems(plan), []
    reqs, sets = listed(plan.get("requirements")), listed(plan.get("change_sets"))
    req_ids, ids = _ids(reqs), _ids(sets)
    problems = size_limit_problems(reqs, sets, max_change_sets) + requirement_problems(reqs) + change_set_id_problems(ids)
    for cs in sets:
        problems += change_set_problems(cs, req_ids, ids, build_kind, max_criteria)
    problems += shared_flag_problems(sets) + uncovered_problems(sets, req_ids) + order_problems(sets, build_kind)
    return problems + secret_problems(plan.get("secrets")), blocking_questions(plan)


def _ancestors(by_id, cs_id):
    seen, todo = set(), list(by_id[cs_id].get("depends_on") or [])
    while todo:
        d = todo.pop()
        if d not in seen and d in by_id:
            seen.add(d)
            todo += by_id[d].get("depends_on") or []
    return seen


def topological_order(change_sets):
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

