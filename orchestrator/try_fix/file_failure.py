
from shared.console import log

from try_fix import file_bug, group_fixes, needs_human, route, write_bug

TARGETS = {"app": "managed_app", "factory": "factory", "info": "info"}


def target_for(verdict, facts, result):
    if verdict.get("target"):
        return verdict["target"]
    if verdict["event"]["source"] in ("build_run", "watchdog") and facts:
        return TARGETS[route.route(route.inferred_category((result or {}).get("category"), facts.get("outcome"), bool(facts.get("bugs"))))]
    return "managed_app"


def hold_story(repo, token, story, cause):
    try:
        needs_human.hold(repo, token, story, f"the bug ticket for it could not be filed ({type(cause).__name__})")
    except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
        log(f"could not hold #{story} for a person either: {type(e).__name__}: {e}")


def decided(v, facts, result):
    return {**v, "target": target_for(v, facts, result), "cause": v.get("cause") or (result or {}).get("category")}


def with_events(members):
    return {**members[0], "events": [m["event"] for m in members]}


def hold_failed_group(repo, token, members, error):
    log(f"could not file the bug for {members[0]['key']}: {type(error).__name__}: {error}")
    story = members[0]["event"].get("story")
    if story and any(m["event"]["severity"] == "failure" for m in members):
        hold_story(repo, token, story, error)


def file_group(repo, token, pat, members, facts, rollback, cfg, cred):
    verdict = with_events(members)
    try:
        doc = write_bug.write(verdict, facts, rollback, cfg, cred)
        return file_bug.file_bug(repo, token, pat, verdict, doc, facts, int(cfg.get("limits", {}).get("fix_attempts_max", 2)))
    except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
        hold_failed_group(repo, token, members, e)
        return {"target": verdict["target"], "action": "needs_human", "number": None, "url": ""}


def file_failures(repo, token, pat, fixes, facts, result, rollback, cfg, key=None, record_spend=None):
    cred, budget = write_bug.mint(cfg, key) if key and "try_fix" in cfg.get("roles", {}) else (None, None)
    out = []
    for members in group_fixes.group([decided(v, facts, result) for v in fixes]):
        got = file_group(repo, token, pat, members, facts, rollback, cfg, cred)
        out += [{"key": m["key"], "source": m["event"]["source"], "severity": m["event"]["severity"], **got} for m in members]
    if budget and cred and record_spend:
        record_spend(budget, cred)
    return out
