IMPROVEMENT_TARGETS = ("managed_app", "factory")


MAX_IMPROVEMENTS = 5


def improvements_from(doc, source):
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
    seen = {(i["target"], i["summary"].lower()) for i in existing}
    return existing + [i for i in new if not ((i["target"], i["summary"].lower()) in seen or seen.add((i["target"], i["summary"].lower())))]
