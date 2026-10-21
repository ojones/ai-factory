from shared import outcomes

from retrospective import run_audit


def render_summary(d):
    icon = ":white_check_mark:" if d["outcome"] in outcomes.OK else ":x:"
    lines = [f"## Build Run Summary: {d['app']}", "",
             f"**Status**: {icon} `{d['outcome']}`  ", f"**Message**: {d['message'] or '-'}  ",
             f"**Cost**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f} cap  ",
             f"**Review passes**: {d['review_passes']}  ", f"**Final commit**: `{d['head_sha'] or '-'}`  ",
             f"**App**: https://{d['app']}.fly.dev  ", f"**Fly log viewer**: https://fly.io/apps/{d['app']}/monitoring", "",
             "| Stage | Agent | Round | Cost | Time (model) | Calls | Peak context | Tokens in (cached) | Tokens out | Condenser calls | Verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    goal = d.get("context_goal_tokens", 100000)
    peaks = []
    for s in d["stages"]:
        u = s.get("usage")
        if u:
            peaks.append((u["peak_context"], f"{s['agent']} {s['round']}"))
            peak = f"{u['peak_context']:,}" + (" :warning:" if u["peak_context"] > goal else "")
            cols = [f"{u.get('seconds', 0):.0f}s ({u.get('llm_seconds', 0):.0f}s)", str(u["calls"]), peak, f"{u['prompt_tokens']:,} ({u['cache_read_tokens']:,})",
                    f"{u['completion_tokens']:,}", str(u["condenser_calls"])]
        else:
            cols = ["-"] * 6
        lines.append(f"| {s['stage']} | {s['agent']} | {s['round']} | ${s['cost_usd']:.4f} | {' | '.join(cols)} | {s['verdict']} |")
    if peaks:
        top, who = max(peaks)
        verdict = "over the goal" if top > goal else "under the goal"
        lines += ["", f"**Peak context this run**: {top:,} tokens ({who}), {verdict} of {goal:,}. "
                  "A peak is the largest prompt in a single LLM call, i.e. how big one Agent's context got."]
    rev = d.get("rollback")
    if rev and rev.get("status") != "skipped":
        lines += ["", "**Rollback**: " + (f"the live app was redeployed from `{str(rev.get('restored', ''))[:8]}` by the app's CI; deploy {rev.get('deploy', 'not checked')}. "
                                       "The run's commits stay in `main` and are fixed forward."
                                       if rev["status"] == "rolled_back" else f"{rev['status']}: {rev.get('reason', '')}")]
    ver = d.get("verification")
    if ver:
        c = ver["counts"]
        lines += ["", f"**Verification** (round {ver['round']}, `{str(ver['sha'])[:8]}`): {c['passed']} passed, {c['failed']} failed, "
                  f"{c['blocked']} blocked, {c['not_run']} not run."]
        if ver.get("limitations"):
            lines += ["", "**Not tested or not cleaned up (limitations)**:"] + [f"- {x}" for x in ver["limitations"]]
    if d.get("audit"):
        lines += run_audit.render_audit(d["audit"]).rstrip("\n").split("\n")
    board = d.get("scoreboard") or []
    if len(board) > 1:
        lines += ["", "**Scoreboard** (checks passed / failed / blocked / not run, blocking findings open):"]
        lines += [f"- round {e['round']}: {e['counts']['passed']} / {e['counts']['failed']} / {e['counts']['blocked']} / "
                  f"{e['counts']['not_run']}, {len(e['blocking'])} open" for e in board]
    rel = d.get("release")
    lines += ["", "**Release**: " + (f"released {', '.join(rel['released']) or 'nothing new'}" if rel else "not released")]
    if d["blocking"] and d["outcome"] not in outcomes.OK:
        lines += ["", "**Open blocking findings at the end**:"] + [f"- [{b['source']}] {b['summary']}" for b in d["blocking"]]
    return "\n".join(lines) + "\n"
