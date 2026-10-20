# Improvements the reviewer and tester suggest for avoiding what they found: validated, capped and merged. The Retrospective files them.



IMPROVEMENT_TARGETS = ("managed_app", "factory")


MAX_IMPROVEMENTS = 5  # per reviewer or tester document, so one noisy model cannot flood the trackers


def improvements_from(doc, source):
    # The system improvements a reviewer or tester suggested: [{source, target, summary, evidence}]. `target` is `managed_app` (the app's
    # own backlog) or `factory` (prompts, template, orchestrator). Anything malformed is dropped; the Agents only suggest, the
    # retrospective decides what is filed.
    items = doc.get("improvements") if isinstance(doc, dict) else None
    found = []
    for i in items if isinstance(items, list) else []:
        if not isinstance(i, dict) or i.get("target") not in IMPROVEMENT_TARGETS:
            continue
        summary = " ".join(str(i.get("summary") or "").split())
        if summary:
            found.append({"source": source, "target": i["target"], "summary": summary[:200],
                          "evidence": " ".join(str(i.get("evidence") or "").split())[:500]})
    return found[:MAX_IMPROVEMENTS]


def merge_improvements(existing, new):
    # `existing` plus the entries of `new` it does not already have (same target and summary, ignoring case and spacing).
    seen = {(i["target"], i["summary"].lower()) for i in existing}
    return existing + [i for i in new if not ((i["target"], i["summary"].lower()) in seen or seen.add((i["target"], i["summary"].lower())))]
