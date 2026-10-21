import base64
import json
import os
import re
import time

from shared import app_state_record, console, shell

from flag_lifecycle import flag_manifest, retirement_check

RUN_ID_RE = re.compile(r"/runs/(\d+)")


def run_id(entry):
    m = RUN_ID_RE.search(entry.get("run_url") or "")
    return int(m.group(1)) if m else 0


def slug_of(key):
    return key.split(".feature.")[-1]


def issue_of(state_flags):
    out = {}
    for f in state_flags:
        try:
            out[slug_of(f["key"])] = int(f["issue"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def age_days(date, today):
    try:
        a, b_ = time.strptime(date, "%Y-%m-%d"), time.strptime(today, "%Y-%m-%d")
        return int((time.mktime(b_) - time.mktime(a)) // 86400)
    except (ValueError, TypeError):
        return None


def candidates(state_flags, manifest, today, min_age_days):
    released = [f for f in state_flags if f.get("state") == "released"]
    newest = max((run_id(f) for f in released), default=0)
    out = []
    for f in released:
        slug, rid, age = slug_of(f["key"]), run_id(f), age_days(f.get("date", ""), today)
        if slug in manifest and rid and rid < newest and age is not None and age >= min_age_days:
            out.append((slug, rid))
    return sorted(set(out), key=lambda c: c[1])


def piggyback_slugs(state_flags, manifest, today, min_age_days, limit):
    return [slug for slug, _ in candidates(state_flags, manifest, today, min_age_days)][:max(0, int(limit))]


def retirement_block(slugs):
    if not slugs:
        return ""
    lines = "\n".join(f"retire-flag: {s}" for s in slugs)
    return ("\n\nAlso in this change, retire the feature flag(s) below. Each has done its job: its change was released and a later release has "
            "come after it. Retire it so users notice no difference: remove the check of the flag and keep the behaviour it guarded, always on; "
            "remove its entry from `flags.json`; delete the tests that assert the flag-off behaviour and keep the tests of the behaviour itself; "
            "leave no code mentioning the slug (a comment may). Touch no other flag. Keep this separate from the main change (its own commit), "
            "and add no flag for it.\n" + lines)


def retirement_note(slugs):
    if not slugs:
        return ""
    return ("\n\nThis change also retires the feature flag(s) " + ", ".join(f"`{s}`" for s in slugs) + ", so the behaviour each guarded is now simply on "
            "for everyone. Check that it still works for an ordinary visitor with no Preview Token, exactly as it did when released, and that "
            "nothing else changed. The task carries `retire-flag: <slug>` lines for them.\n" + "\n".join(f"retire-flag: {s}" for s in slugs))


def app_flags(owner, app, pat):
    env = {**os.environ, "GH_TOKEN": pat}
    out = shell.sh(["gh", "issue", "list", "--repo", f"{owner}/{app}", "--label", app_state_record.STATE_LABEL, "--state", "open", "--json", "body"], env=env, check=False).stdout
    found = json.loads(out or "[]")
    if not found:
        return None, None
    content = shell.sh(["gh", "api", f"repos/{owner}/{app}/contents/flags.json", "--jq", ".content"], env=env, check=False)
    if content.returncode != 0:
        return None, None
    try:
        slugs = flag_manifest.manifest_slugs(base64.b64decode(content.stdout).decode())
    except ValueError:
        return None, None
    return app_state_record.load(found[0]["body"]).get("flags", []), slugs


def choose(eligible, task, owner, app, pat, limits, head_flags_json, today):
    named = retirement_check.retire_slugs(task)
    picked, issues = [], {}
    if eligible:
        try:
            state_flags, manifest_now = app_flags(owner, app, pat)
            if state_flags is not None:
                issues = issue_of(state_flags)
                picked = piggyback_slugs(state_flags, manifest_now, today, int(limits.get("min_age_days", 1)), limits.get("piggyback_max", 5))
        except Exception as e:  # noqa: BLE001 - retiring is never a reason to stop the run
            console.log(f"could not choose flags to retire: {type(e).__name__}: {e}")
    in_repo = flag_manifest.manifest_slugs(head_flags_json)
    return [s for s in dict.fromkeys(named + picked) if s in in_repo], issues
