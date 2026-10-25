MAX_ITEMS = 5


def clip(text, n=300):
    return " ".join(str(text or "").split())[:n]


def rollback_line(rollback):
    if not rollback:
        return "No rollback was attempted."
    status = rollback.get("status")
    if status == "rolled_back":
        return (f"The live app was redeployed from `{str(rollback.get('restored', ''))[:8]}` (the version before this run) by the app's CI; "
                f"the deploy is **{rollback.get('deploy', 'not checked')}**. Nothing was reverted in git: this run's commits are still in `main`, behind a flag that is off.")
    if status == "failed":
        return (f"**The automatic rollback failed** ({clip(rollback.get('reason'))}). The live app may still be running the regressing version; "
                "redeploy the previous version by hand (run `rollback-fly.yml` for the commit before this run).")
    return f"Nothing was rolled back: {clip(rollback.get('reason'), 200)}."


def rollback_requirements(facts, rollback):
    status = (rollback or {}).get("status")
    if status == "failed":
        return ["The live app is back on the version before this run (the automatic rollback failed and has to be done by hand), "
                "and it answers every route as it did before the run."]
    if status == "rolled_back":
        return ["Confirm the app behaves exactly as before the run (the previous version was redeployed; check the routes this run touched)."]
    if facts.get("commits") and facts.get("outcome") == "regression":
        return ["Check that the live app is on the version you want: the tester found a regression and no rollback was done "
                f"({clip((rollback or {}).get('reason'), 120) or 'no reason recorded'})."]
    return []


def bug_requirement(x):
    seen = "behaviour that was live before the change" if x.get("kind") == "regression" else "the new change, still dark"
    repro = f" Repro: {clip(x.get('repro'), 160)}." if x.get("repro") else ""
    return (f"Fix this bug the tester saw ({seen}): {clip(x.get('check'), 160)}. Evidence: {clip(x.get('evidence'), 200) or 'none given'}."
            + repro + " Add a test that fails without the fix.")


def flag_missing_requirement(facts, message):
    slugs = ", ".join(f"`{n.get('slug')}`" for n in facts.get("flag_notes") or []) or "the change's flag"
    return (f"The change is released behind a flag that exists in GrowthBook ({message}): use exactly the flag the task names for the story and add no other, so "
            f"{slugs} can be switched on. Nothing was rolled back; the code is still in `main`, dark, so fix it forward.")


def outcome_requirement(facts):
    outcome, message = facts.get("outcome"), clip(facts.get("message"), 200)
    blocking = [clip(s, 160) for s in facts.get("final_blocking") or []][:MAX_ITEMS]
    if outcome in ("round_limit",):
        return "The same request ends in a clean pass within the configured review rounds" + (f", without these blocking findings recurring: {'; '.join(blocking)}." if blocking else ".")
    if outcome in ("budget_exhausted", "time_limit"):
        return f"The same request finishes inside its cost cap and time limit (it stopped because: {message}), or is split into smaller requests that each do."
    if outcome == "crash":
        return f"The run no longer crashes (it stopped with: {message})."
    if outcome == "regression":
        return f"The regression is fixed ({message}): the behaviour the tester found broken works again with the change in place, and a test covers it. The code is still in `main` (nothing was reverted), so fix it forward; the flag is released only after a clean pass."
    if outcome == "flag_missing":
        return flag_missing_requirement(facts, message)
    if outcome == "watchdog_disabled":
        return f"The regression the watchdog found is fixed ({message}). The flag it switched off is dead: remove it from flags.json together with the code it guarded, and deliver the corrected change behind a new flag of its own, which is released only after a clean pass."
    return f"Whatever stopped the run is resolved: {message}."


def recurring_requirements(facts):
    recurring = facts.get("recurring_findings") or []
    if not recurring or facts.get("outcome") in ("round_limit",):
        return []
    return ["These findings, which the coder did not resolve across rounds, stop recurring: " + "; ".join(clip(s, 100) for s in recurring[:MAX_ITEMS]) + "."]


def agent_requirements(result):
    return [clip(r, 300) for r in (result or {}).get("requirements") or [] if isinstance(r, str) and r.strip()]


def requirements(facts, result, rollback, app_side=False):
    reqs = rollback_requirements(facts, rollback) + [bug_requirement(x) for x in (facts.get("bugs") or [])[:MAX_ITEMS]]
    reqs += [outcome_requirement(facts)] + recurring_requirements(facts)
    for r in [] if app_side else agent_requirements(result):
        reqs += [] if r in reqs else [r]
    reqs.append("A re-run of the same request ends `released` or `nothing_to_release` without anyone editing code by hand.")
    return reqs[:MAX_ITEMS + 3]
