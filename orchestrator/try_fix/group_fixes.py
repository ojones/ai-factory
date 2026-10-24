def group_key(verdict):
    ev = verdict["event"]
    if not ev.get("story"):
        return verdict["key"]
    return (ev["app"], ev["story"], verdict["target"])


def group(verdicts):
    groups = {}
    for v in verdicts:
        groups.setdefault(group_key(v), []).append(v)
    return list(groups.values())
