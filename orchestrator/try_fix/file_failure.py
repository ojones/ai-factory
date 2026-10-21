# What happens to the events the Retrospective judged worth fixing (STEP 6.2 to 7.x): for each, the target (the verdict's, else by the cause: try_fix/route.py), the
# bug text (the Try Fix Agent, write_bug.py, one credential for the whole batch) and the filing (file_bug.py). An unchanged child is never started again. Never raises.
import contextlib

from shared.console import log

from try_fix import file_bug, needs_human, route, write_bug

TARGETS = {"app": "managed_app", "factory": "factory", "info": "info"}


def target_for(verdict, facts, result):
    # The verdict's own target when the Retrospective named one; otherwise a run's failure is routed by its cause, and anything else is the app's.
    if verdict.get("target"):
        return verdict["target"]
    if verdict["event"]["source"] in ("build_run", "watchdog") and facts:
        return TARGETS[route.route(route.inferred_category((result or {}).get("category"), facts.get("outcome"), bool(facts.get("bugs"))))]
    return "managed_app"


def file_failures(repo, token, pat, fixes, facts, result, rollback, cfg, key=None, record_spend=None):
    # One result per `fix` verdict: {"key", "source", "severity", "target", "action", "url", "number"}.
    lim = cfg.get("limits", {})
    cred, budget = write_bug.mint(cfg, key) if key and "try_fix" in cfg.get("roles", {}) else (None, None)
    out = []
    for v in fixes:
        cause = v.get("cause") or (result or {}).get("category")
        verdict = {**v, "target": target_for(v, facts, result), "cause": cause}
        try:
            doc = write_bug.write(verdict, facts, rollback, cfg, cred)
            got = file_bug.file_bug(repo, token, pat, verdict, doc, facts, int(lim.get("fix_attempts_max", 2)))
        except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
            log(f"could not file the bug for {v['key']}: {type(e).__name__}: {e}")
            story = v["event"].get("story")
            if story and v["event"]["severity"] == "failure":
                with contextlib.suppress(Exception):
                    needs_human.hold(repo, token, story, f"the bug ticket for it could not be filed ({type(e).__name__})")
            got = {"target": verdict["target"], "action": "needs_human", "number": None, "url": ""}
        out.append({"key": v["key"], "source": v["event"]["source"], "severity": v["event"]["severity"], **got})
    if budget and cred and record_spend:
        record_spend(budget, cred)
    return out
