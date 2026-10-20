# STEP 8.1, 8.2, 8.4: is a bug dark or released? The answer comes from the flag's state in the App State record (the issue in the app's repo that the Build Run
# keeps, shared/app_state_record.py), never from a guess. A flag that was released and is still on is released (a bug now is a regression, a fresh flag); one that was
# never released, is off, or was switched off by the watchdog is dark (the fix keeps the flag, the story stays open). An error with no flag in it cannot be tied to a
# story, so nothing is claimed about it (`released` stays unknown) and it is filed as a plain bug Intake. Pure, tested alone.
import re

SLUG = re.compile(r"\bissue-(\d+)\b")


def flag_states(state_data):
    # {issue number: "released" | "dark"} for every flag the App State lists. "released" is the state the release step records; every other state ("switched off by the
    # watchdog", "dark (failed its checks; ...)") is dark.
    out = {}
    for f in (state_data or {}).get("flags") or []:
        m = SLUG.search(str(f.get("key") or ""))
        if m:
            out[int(m.group(1))] = "released" if f.get("state") == "released" else "dark"
    return out


def attach(entry_text, states):
    # (story, flag slug, released) for the first flag named in a log entry that the App State knows, else (None, None, None).
    for m in SLUG.finditer(entry_text or ""):
        story = int(m.group(1))
        if story in states:
            return story, m.group(0), states[story] == "released"
    return None, None, None
