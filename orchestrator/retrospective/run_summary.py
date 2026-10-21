from shared import outcomes

from retrospective import run_audit

STAGE_HEADER = ["| Stage | Agent | Round | Cost | Time (model) | Calls | Peak context | Tokens in (cached) | Tokens out | Condenser calls | Verdict |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]


def headline(d):
    icon = ":white_check_mark:" if d["outcome"] in outcomes.OK else ":x:"
    return [f"## Build Run Summary: {d['app']}", "",
            f"**Status**: {icon} `{d['outcome']}`  ", f"**Message**: {d['message'] or '-'}  ",
            f"**Cost**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f} cap  ",
            f"**Review passes**: {d['review_passes']}  ", f"**Final commit**: `{d['head_sha'] or '-'}`  ",
            f"**App**: https://{d['app']}.fly.dev  ", f"**Fly log viewer**: https://fly.io/apps/{d['app']}/monitoring", ""]


def usage_columns(usage, goal):
    if not usage:
        return ["-"] * 6
    peak = f"{usage['peak_context']:,}" + (" :warning:" if usage["peak_context"] > goal else "")
    return [f"{usage.get('seconds', 0):.0f}s ({usage.get('llm_seconds', 0):.0f}s)", str(usage["calls"]), peak,
            f"{usage['prompt_tokens']:,} ({usage['cache_read_tokens']:,})", f"{usage['completion_tokens']:,}", str(usage["condenser_calls"])]


def stage_row(s, goal):
    cols = usage_columns(s.get("usage"), goal)
    return f"| {s['stage']} | {s['agent']} | {s['round']} | ${s['cost_usd']:.4f} | {' | '.join(cols)} | {s['verdict']} |"


def peak_context_lines(d, goal):
    peaks = [(s["usage"]["peak_context"], f"{s['agent']} {s['round']}") for s in d["stages"] if s.get("usage")]
    if not peaks:
        return []
    top, who = max(peaks)
    verdict = "over the goal" if top > goal else "under the goal"
    return ["", f"**Peak context this run**: {top:,} tokens ({who}), {verdict} of {goal:,}. "
            "A peak is the largest prompt in a single LLM call, i.e. how big one Agent's context got."]


def stage_lines(d):
    goal = d.get("context_goal_tokens", 100000)
    return STAGE_HEADER + [stage_row(s, goal) for s in d["stages"]] + peak_context_lines(d, goal)


def rollback_lines(d):
    rev = d.get("rollback")
    if not rev or rev.get("status") == "skipped":
        return []
    if rev["status"] != "rolled_back":
        return ["", f"**Rollback**: {rev['status']}: {rev.get('reason', '')}"]
    return ["", f"**Rollback**: the live app was redeployed from `{str(rev.get('restored', ''))[:8]}` by the app's CI; deploy {rev.get('deploy', 'not checked')}. "
            "The run's commits stay in `main` and are fixed forward."]


def verification_lines(d):
    ver = d.get("verification")
    if not ver:
        return []
    c = ver["counts"]
    lines = ["", f"**Verification** (round {ver['round']}, `{str(ver['sha'])[:8]}`): {c['passed']} passed, {c['failed']} failed, {c['blocked']} blocked, {c['not_run']} not run."]
    if ver.get("limitations"):
        lines += ["", "**Not tested or not cleaned up (limitations)**:"] + [f"- {x}" for x in ver["limitations"]]
    return lines


def scoreboard_lines(d):
    board = d.get("scoreboard") or []
    if len(board) <= 1:
        return []
    return (["", "**Scoreboard** (checks passed / failed / blocked / not run, blocking findings open):"]
            + [f"- round {e['round']}: {e['counts']['passed']} / {e['counts']['failed']} / {e['counts']['blocked']} / {e['counts']['not_run']}, {len(e['blocking'])} open" for e in board])


def release_lines(d):
    rel = d.get("release")
    return ["", "**Release**: " + (f"released {', '.join(rel['released']) or 'nothing new'}" if rel else "not released")]


def open_blocking_lines(d):
    if not d["blocking"] or d["outcome"] in outcomes.OK:
        return []
    return ["", "**Open blocking findings at the end**:"] + [f"- [{b['source']}] {b['summary']}" for b in d["blocking"]]


def audit_lines(d):
    return run_audit.render_audit(d["audit"]).rstrip("\n").split("\n") if d.get("audit") else []


def render_summary(d):
    sections = (headline(d), stage_lines(d), rollback_lines(d), verification_lines(d), audit_lines(d), scoreboard_lines(d), release_lines(d), open_blocking_lines(d))
    return "\n".join(line for section in sections for line in section) + "\n"
