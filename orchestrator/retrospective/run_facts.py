import hashlib
import json
from pathlib import Path

from flag_lifecycle import dark_feature
from shared import agent_output

from retrospective import tracker


def read_rounds(work):
    rounds, seen, final_minor = [], {}, []
    for path in sorted(Path(work).glob("findings-*.json"), key=lambda p: p.name):
        doc = agent_output.load_json(path) or {}
        if not doc.get("blocking") and not doc.get("round") and not doc.get("minor"):
            continue
        final_minor = doc.get("minor") or []
        entry = {"round": doc.get("round"), "blocking": [f.get("summary", "") for f in doc.get("blocking", [])],
                 "tester_blocking": [f.get("summary", "") for f in doc.get("blocking", []) if f.get("source") == "tester"]}
        rounds.append(entry)
        for s in entry["blocking"]:
            seen.setdefault(tracker.normalize(s), []).append(entry["round"])
    return rounds, sorted(k for k, v in seen.items() if len(v) > 1), final_minor


def stage_summaries(d):
    return [{"stage": s["stage"], "round": s["round"], "verdict": s["verdict"], "cost_usd": s["cost_usd"],
             "seconds": (s.get("usage") or {}).get("seconds"), "calls": (s.get("usage") or {}).get("calls")} for s in d.get("stages", [])]


def dict_entries(d, key, required):
    return [x for x in d.get(key) or [] if isinstance(x, dict) and x.get(required)]


def collect_facts(work, d):
    rounds, recurring, final_minor = read_rounds(work)
    return {"app": d.get("app"), "outcome": d.get("outcome"), "message": d.get("message"),
            "run_url": d.get("run_url"), "issue_number": d.get("issue_number"), "spent_usd": d.get("spent_usd"),
            "commits": d.get("commits", []), "flags": d.get("flags") or [], "cap_usd": d.get("cap_usd"), "review_passes": d.get("review_passes") or 0,
            "audit": d.get("audit") or [], "rollback": d.get("rollback"), "plan": d.get("plan"), "intake_kind": d.get("intake_kind"),
            "final_blocking": [f.get("summary", "") for f in d.get("blocking", [])],
            "rounds": rounds, "recurring_findings": recurring, "stages": stage_summaries(d),
            "final_minor": [{k: f.get(k, "") for k in ("summary", "evidence", "file", "line")} for f in final_minor],
            "improvements": dict_entries(d, "improvements", "summary"),
            "dark_broken": dark_feature.is_dark_broken(d), "flag_notes": d.get("flag_notes") or [],
            "unverified": dict_entries(d, "unverified", "check"), "bugs": dict_entries(d, "bugs", "check")}


def last_stage(facts):
    return facts["stages"][-1]["stage"] if facts["stages"] else ""


def fingerprint(facts):
    basis = facts["recurring_findings"] or sorted(tracker.normalize(s) for s in facts["final_blocking"])
    return hashlib.sha1(json.dumps([facts["outcome"], last_stage(facts), basis]).encode()).hexdigest()[:8]


def render_facts(facts):
    lines = [f"**App**: {facts['app']}  ", f"**Outcome**: `{facts['outcome']}`: {facts['message']}  ",
             f"**Run**: {facts['run_url']}  ", f"**Intake**: ai-factory#{facts['issue_number']}  ",
             f"**Spent**: ${facts['spent_usd'] or 0:.4f}", ""]
    for r in facts["rounds"]:
        lines += [f"Round {r['round']} blocking:"] + [f"- {s}" for s in r["blocking"]] + [""]
    if facts["recurring_findings"]:
        lines += ["Recurred across rounds (the coder did not resolve these):"] + [f"- {s}" for s in facts["recurring_findings"]] + [""]
    if facts["final_minor"]:
        lines += ["Minor findings still open at the end:"] + [f"- {m['summary']}" for m in facts["final_minor"]] + [""]
    lines += ["| Stage | Round | Verdict | Cost | Seconds | Calls |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['stage']} | {s['round']} | {s['verdict']} | ${s['cost_usd']:.4f} | {s['seconds'] or '-'} | {s['calls'] or '-'} |"
              for s in facts["stages"]]
    return "\n".join(lines) + "\n"


def title_for(facts):
    return f"Stuck run [{facts['outcome']}] {fingerprint(facts)}"
