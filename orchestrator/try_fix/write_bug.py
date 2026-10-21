# STEP 7.6: write the bug ticket's text for an event the retrospective judged worth fixing. The Try Fix Agent has one job: how it was found, the cause (already
# named, never decided here), what it takes to resolve and checkable requirements. It is one model call with no tools under its own capped credential; the
# answer is validated (validate_bug.py), and when there is no key, the call fails or the answer is unusable the Orchestrator writes the same four fields from
# the facts (fallback), so a filing never depends on the model. It plans nothing and splits nothing: that is the planner's job.
import json

from shared import model_call, prompts, spend_budget, spend_ledger
from shared.console import log

from try_fix import failure_text, validate_bug

SOURCE_TEXT = {"build_run": "a Build Run that ended badly", "watchdog": "the watchdog after a release", "reviewer": "the reviewer during a Build Run",
               "tester": "the tester during a Build Run", "staging": "a staging check", "production_feedback": "a scan of the deployed app's logs",
               "escaped_defect": "an escaped-defect report by the app's owner"}


GUIDANCE = {
    "spec_ambiguity": ("Nobody is available to answer questions. Where the request is ambiguous or contradicts itself, choose the most conservative "
                       "reading (keep existing data and behaviour, remove nothing permanently, keep the change behind its flag) and state the "
                       "choice as an assumption."),
    "model_limit": "The last attempt was too much for one pass. Do the smallest part that is independently valuable and keep it small.",
    "regression": ("The change broke something: the watchdog switched its flag off, or the tester saw checks fail (they are listed under the requirements). "
                   "Find what is wrong (the error lines or the failing checks, the diff and the tests), fix the code, and add a test that "
                   "fails without the fix. Do not remove the flag or the feature."),
}


def scrubbed(verdict):
    # The verdict with secret-shaped text taken out of the event (a log excerpt can hold one), before anything else reads it.
    ev = {**verdict["event"], **{k: validate_bug.scrub(verdict["event"].get(k)) for k in ("summary", "evidence")}}
    return {**verdict, "event": ev}


def fallback(verdict, facts=None, rollback=None, max_criteria=6):
    # The ticket text from the facts alone: the same four fields the Agent writes.
    ev, facts = verdict["event"], facts or {}
    where = f" ({facts['run_url']})" if facts.get("run_url") else (f" ({ev['evidence']})" if ev.get("source") in ("staging", "production_feedback", "escaped_defect") and ev.get("evidence") else "")
    cause = verdict.get("cause")
    if ev["source"] in ("build_run", "watchdog") and facts.get("outcome"):
        reqs = failure_text.requirements(facts, {"category": cause}, rollback, app_side=verdict.get("target") != "factory")
        reqs = reqs if len(reqs) <= max_criteria else reqs[:max_criteria - 1] + [reqs[-1]]
    else:
        reqs = [f"This no longer happens: {ev['summary'][:200]}", "A test covers the fixed behaviour and fails without the fix."]
    return {"how_found": f"Found by {SOURCE_TEXT.get(ev['source'], ev['source'])}: {ev['summary']}{where}.",
            "root_cause": (f"The retrospective named the cause as {cause}. " if cause else "No cause was named. ") + (verdict.get("reason") or ""),
            "what_it_takes": [f"Resolve: {ev['summary'][:200]}"] + ([GUIDANCE[cause]] if cause in GUIDANCE else []), "requirements": reqs, "source": "fallback"}


def agent_input(verdict, facts, rollback):
    ev, facts = verdict["event"], facts or {}
    context = {k: facts.get(k) for k in ("outcome", "message", "run_url", "final_blocking", "recurring_findings", "bugs", "flag_notes") if facts.get(k)}
    if rollback:
        context["rollback"] = failure_text.rollback_line(rollback)
    return json.dumps({"decision": {"target": verdict.get("target"), "cause": verdict.get("cause"), "reason": verdict.get("reason")},
                       "event": {k: ev.get(k) for k in ("source", "severity", "summary", "evidence")}, "context": context}, indent=2)[:12000]


def mint(cfg, parent_key):
    # (credential, budget) limited to `try_fix_cost_cap_usd`, or (None, None).
    try:
        lim = cfg["limits"]
        budget = spend_budget.Budget(parent_key, float(lim.get("try_fix_cost_cap_usd", 0.25)), int(lim["jwt_ttl_seconds"]))
        return budget.mint(cfg["roles"]["try_fix"]["model"]), budget
    except Exception as e:  # noqa: BLE001 - never fail the run
        log(f"could not mint a credential for the Try Fix Agent: {type(e).__name__}")
        return None, None


def write(verdict, facts, rollback, cfg, key, ask=model_call.json_chat):
    # {how_found, root_cause, what_it_takes, requirements, source: "agent" | "fallback"}; never raises. `key` is the Agent's own credential.
    verdict = scrubbed(verdict)
    max_criteria = int(cfg.get("limits", {}).get("planner_max_criteria", 6))
    plain = fallback(verdict, facts, rollback, max_criteria)
    role = cfg.get("roles", {}).get("try_fix")
    if not key or not role:
        return plain
    try:
        prompt = prompts.render(prompts.load_prompt(role["prompt"]), {"input": agent_input(verdict, facts, rollback), "max_criteria": max_criteria})
        doc, problems = validate_bug.check(ask(cfg["provider"]["base_url"], key, role["model"], "You write bug tickets and answer with JSON only.", prompt), max_criteria)
    except Exception as e:  # noqa: BLE001 - the ticket is still written
        log(f"the Try Fix Agent failed ({type(e).__name__}); the Orchestrator writes the ticket")
        return plain
    if problems:
        log("the Try Fix Agent's ticket was not usable (" + "; ".join(problems) + "); the Orchestrator writes it")
        return plain
    return {**doc, "source": "agent"}


def record_spend(budget, key, repo, token, run_id):
    # What the Agent spent goes to the spend ledger under its own id (best effort).
    try:
        spent = budget.refresh(key)
        spend_ledger.record_spend_in_ledger({"app": "try-fix", "spent_usd": spent}, repo, f"{run_id}-tf", token)
    except Exception as e:  # noqa: BLE001
        log(f"could not record the Try Fix Agent's spend: {type(e).__name__}")
