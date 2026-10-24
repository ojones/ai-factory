VERDICTS = ("fix", "record")
TARGETS = ("managed_app", "factory")


def parse(result):
    entries = (result or {}).get("events")
    if not isinstance(entries, list):
        return {}
    return {str(e["key"]): e for e in entries if isinstance(e, dict) and e.get("key")}


def fix_cap(limits):
    return int((limits or {}).get("bugs_per_app_per_day", 2))


def decide(events, agent_entries=None, limits=None, fixed_today=0):
    lim, entries, used = limits or {}, agent_entries or {}, int(fixed_today)
    cap = fix_cap(lim)
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
            verdict, why = "record", f"the daily limit of {cap} bug tickets for this app is used"
        else:
            verdict, why = "record", reason or ("a fix needs a reason" if asked == "fix" else "no fix was asked for")
        target = said.get("target") if said.get("target") in TARGETS else None
        out.append({"key": ev["key"], "verdict": verdict, "target": target, "cause": said.get("cause") or None, "reason": why, "event": ev})
    return out


def fix_events(verdicts):
    return [v for v in verdicts if v["verdict"] == "fix"]


def render(verdicts):
    lines = [f"- `{v['key']}` {v['event']['severity']}: {v['event']['summary'][:100]} -> **{v['verdict']}** ({v['target'] or 'target by cause'}): {v['reason']}" for v in verdicts]
    return "\n".join(lines)
