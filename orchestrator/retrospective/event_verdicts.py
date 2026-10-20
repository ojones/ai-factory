# STEP 6.2, 6.7: the Retrospective's verdict on each failure event. The Agent names, per event, a verdict (`fix` or `record`), a target (`managed_app` or
# `factory`), a cause and a reason; this file turns that, or the lack of it, into a verdict for every event. The rules are code, not prompt:
#   a failure is always fixed (the Agent cannot downgrade it); a warning is fixed only when the Agent says `fix` and gives a reason;
#   with no answer a failure is `fix` and a warning is `record`; at most `fix_events_per_app_per_day` warnings are fixed per app per day.
VERDICTS = ("fix", "record")
TARGETS = ("managed_app", "factory")


def parse(result):
    # {event key: the Agent's entry} from the Agent's result, ignoring anything malformed.
    entries = (result or {}).get("events")
    if not isinstance(entries, list):
        return {}
    return {str(e["key"]): e for e in entries if isinstance(e, dict) and e.get("key")}


def decide(events, agent_entries=None, limits=None, fixed_today=0):
    # One verdict per event: {key, verdict, target, cause, reason, event}. `fixed_today` counts the warnings already fixed for the app today.
    lim, entries, used = limits or {}, agent_entries or {}, int(fixed_today)
    cap = int(lim.get("fix_events_per_app_per_day", 3))
    out = []
    for ev in events:
        said = entries.get(ev["key"]) or {}
        asked = said.get("verdict") if said.get("verdict") in VERDICTS else None
        reason = " ".join(str(said.get("reason") or "").split())[:300]
        if ev["severity"] == "failure":
            verdict, why = "fix", reason or "a failure is always fixed"
        elif asked == "fix" and reason and used < cap:
            verdict, why, used = "fix", reason, used + 1
        elif asked == "fix" and reason:
            verdict, why = "record", f"the daily limit of {cap} fixed warnings for this app is used"
        else:
            verdict, why = "record", reason or ("a fix needs a reason" if asked == "fix" else "no fix was asked for")
        target = said.get("target") if said.get("target") in TARGETS else None  # none named: the filing falls back to the cause (try_fix/route.py)
        out.append({"key": ev["key"], "verdict": verdict, "target": target, "cause": said.get("cause") or None, "reason": why, "event": ev})
    return out


def fix_events(verdicts):
    return [v for v in verdicts if v["verdict"] == "fix"]


def render(verdicts):
    lines = [f"- `{v['key']}` {v['event']['severity']}: {v['event']['summary'][:100]} -> **{v['verdict']}** ({v['target'] or 'target by cause'}): {v['reason']}" for v in verdicts]
    return "\n".join(lines)
