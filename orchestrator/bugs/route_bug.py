import re

SLUG = re.compile(r"\bissue-(\d+)\b")


def flag_states(state_data):
    out = {}
    for f in (state_data or {}).get("flags") or []:
        m = SLUG.search(str(f.get("key") or ""))
        if m:
            out[int(m.group(1))] = "released" if f.get("state") == "released" else "dark"
    return out


def attach(entry_text, states):
    for m in SLUG.finditer(entry_text or ""):
        story = int(m.group(1))
        if story in states:
            return story, m.group(0), states[story] == "released"
    return None, None, None
