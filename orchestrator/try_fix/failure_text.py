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


def requirements(facts, result, rollback, app_side=False):
    outcome, message = facts.get("outcome"), clip(facts.get("message"), 200)
    reqs = []
    status = (rollback or {}).get("status")
    if status == "failed":
        reqs.append("The live app is back on the version before this run (the automatic rollback failed and has to be done by hand), "
                    "and it answers every route as it did before the run.")
    elif status == "rolled_back":
        reqs.append("Confirm the app behaves exactly as before the run (the previous version was redeployed; check the routes this run touched).")
    elif facts.get("commits") and outcome == "regression":
        reqs.append("Check that the live app is on the version you want: the tester found a regression and no rollback was done "
                    f"({clip((rollback or {}).get('reason'), 120) or 'no reason recorded'}).")
    for x in (facts.get("bugs") or [])[:MAX_ITEMS]:
        reqs.append(f"Fix this bug the tester saw ({'behaviour that was live before the change' if x.get('kind') == 'regression' else 'the new change, still dark'}): "
                    f"{clip(x.get('check'), 160)}. Evidence: {clip(x.get('evidence'), 200) or 'none given'}."
                    + (f" Repro: {clip(x.get('repro'), 160)}." if x.get("repro") else "") + " Add a test that fails without the fix.")
    recurring = facts.get("recurring_findings") or []
    blocking = [clip(s, 160) for s in facts.get("final_blocking") or []][:MAX_ITEMS]
    if outcome in ("round_limit", "stuck"):
        reqs.append("The same request ends in a clean pass within the configured review rounds" +
                    (f", without these blocking findings recurring: {'; '.join(blocking)}." if blocking else "."))
    elif outcome in ("budget_exhausted", "time_limit"):
        reqs.append(f"The same request finishes inside its cost cap and time limit (it stopped because: {message}), or is split into smaller requests that each do.")
    elif outcome == "crash":
        reqs.append(f"The run no longer crashes (it stopped with: {message}).")
    elif outcome == "regression":
        reqs.append(f"The regression is fixed ({message}): the behaviour the tester found broken works again with the change in place, and a test covers it. The code is still in `main` (nothing was reverted), so fix it forward; the flag is released only after a clean pass.")
    elif outcome == "flag_missing":
        notes = facts.get("flag_notes") or []
        slugs = ", ".join(f"`{n.get('slug')}`" for n in notes) or "the change's flag"
        reqs.append(f"The change is released behind a flag that exists in GrowthBook ({message}): use exactly the flag the task names for the story and add no other, so "
                    f"{slugs} can be switched on. Nothing was rolled back; the code is still in `main`, dark, so fix it forward.")
    elif outcome == "watchdog_disabled":
        reqs.append(f"The regression the watchdog found is fixed ({message}). The flag it switched off is dead: remove it from flags.json together with the code it guarded, and deliver the corrected change behind a new flag of its own, which is released only after a clean pass.")
    else:
        reqs.append(f"Whatever stopped the run is resolved: {message}.")
    if recurring and outcome not in ("round_limit", "stuck"):
        reqs.append("These findings, which the coder did not resolve across rounds, stop recurring: " + "; ".join(clip(s, 100) for s in recurring[:MAX_ITEMS]) + ".")
    for r in ((result or {}).get("requirements") or []) if not app_side else []:
        if isinstance(r, str) and r.strip() and clip(r, 300) not in reqs:
            reqs.append(clip(r, 300))
    reqs.append("A re-run of the same request ends `released` or `nothing_to_release` without anyone editing code by hand.")
    return reqs[:MAX_ITEMS + 3]


def render(facts, result, rollback, target, intake_url=""):
    cat = (result or {}).get("category")
    lines = ["## What happened", "",
             f"The Build Run for `{facts.get('app')}` ended **{facts.get('outcome')}**: {clip(facts.get('message'), 400)}", "",
             f"- Run: {facts.get('run_url')}", f"- Request: {intake_url or '#' + str(facts.get('issue_number'))}",
             f"- Review passes: {facts.get('review_passes', 0)}; spent ${(facts.get('spent_usd') or 0):.2f} of a ${(facts.get('cap_usd') or 0):.2f} cap"]
    for s in [clip(x, 200) for x in facts.get("final_blocking") or []][:MAX_ITEMS]:
        lines.append(f"- Still blocking at the end: {s}")
    lines += ["", "## What was done automatically", "", rollback_line(rollback), "", "## Analysis (automated, and may be wrong)", ""]
    if cat:
        lines.append(f"The retrospective named the cause as **{cat}**: {clip((result or {}).get('root_cause'), 500)}")
        if (result or {}).get("change_summary") and result["change_summary"] != "none":
            lines.append(f"\nIt proposed: {clip(result['change_summary'], 400)}")
    else:
        lines.append("The retrospective did not name a cause (it did not run or produced no usable analysis).")
    lines += ["", "## Requirements", ""] + [f"{i}. {r}" for i, r in enumerate(requirements(facts, result, rollback), 1)]
    lines += ["", "## How this is picked up", ""]
    if target == "factory":
        lines.append(f"This is a fault in the Factory itself ({cat}). The retrospective Agent proposes a pull request; when it merges, the child that failed starts again "
                     "by itself. Add the label `ready-for-factory-run` to ask the Factory Run for another try.")
    else:
        lines.append("No cause was named, or it was infrastructure. Read the run and decide; nothing runs until the child that failed is edited and given `proceed-with-change` again.")
    return "\n".join(lines) + "\n"
