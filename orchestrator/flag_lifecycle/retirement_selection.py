# Flag retirement: a feature flag is short-lived, so once a change is proven in production its flag is removed, by itself.
#
# A flag exists for one job: to stage a change dark and release it when it is safe (STANDARDS-FEATURE-FLAGS.md). Nobody uses it for
# anything else, so once a *later* Build Run has also released something, the earlier release has been replaced by a newer one and its
# flag has done its job. A retirement is never a run of its own (that would spend a planner, reviewer, tester, CI and a deploy on a change
# that only deletes a check): the next Update App Intake for the same app carries it. At the start of that Build Run the Orchestrator picks
# the oldest eligible flag (`piggyback_slugs`) and adds a "retire these flags in the same change" block to the coder's task; the tester is
# told to check that the behaviour is still on for everyone, and the run archives the flag in GrowthBook when it ends well. Users see no
# change. The owner's standing approval is the standard; nobody reviews a retirement.
#
# A flag is a candidate when all of these hold, read from the app's State issue and `flags.json`:
#   - it is in `flags.json` and the State issue records it as `released` (not one the watchdog switched off: that one is dead, and the fix
#     request replaces it with a new flag);
#   - a later Build Run of the app also released a flag (its run id is higher);
#   - it was released on an earlier day than today (a soak of at least a day, so the production-feedback scans have looked at it).
# The newest release therefore always keeps its flag, and a run that ended `nothing_to_release` retires nothing.
#
# A *dark* feature is the other case: a flagged change that never got through its checks. It stays dark, behind its flag, and is fixed forward
# by the story's automatic retries (`fix_attempts_max`). Only after those are used up (the story is labelled `needs-human` and
# `dark-broken`) and a person adds the label `approve-retire` to the story is it removed: `approve` files an Update App Intake that deletes the
# flag's check, the code it guarded, its tests and its line in `flags.json`, and starts it. Nothing removes a dark feature on its own.
#
# Limits: `limits.flag_retirement` in agents/profiles.yml (`piggyback_max` flags per run, default 5, so a backlog clears; `min_age_days`).
#
# This file: which proven flags ride along, and the text that tells the coder and tester about them.
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
    # {slug: story issue number} for the flags the State issue knows the story of.
    out = {}
    for f in state_flags:
        try:
            out[slug_of(f["key"])] = int(f["issue"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def age_days(date, today):
    # Whole days between two YYYY-MM-DD strings, or None if either cannot be read.
    try:
        a, b_ = time.strptime(date, "%Y-%m-%d"), time.strptime(today, "%Y-%m-%d")
        return int((time.mktime(b_) - time.mktime(a)) // 86400)
    except (ValueError, TypeError):
        return None


def candidates(state_flags, manifest, today, min_age_days):
    # The flags to retire, oldest release first: [(slug, run id)]. See the module docstring for the rules.
    released = [f for f in state_flags if f.get("state") == "released"]
    newest = max((run_id(f) for f in released), default=0)
    out = []
    for f in released:
        slug, rid, age = slug_of(f["key"]), run_id(f), age_days(f.get("date", ""), today)
        if slug in manifest and rid and rid < newest and age is not None and age >= min_age_days:
            out.append((slug, rid))
    return sorted(set(out), key=lambda c: c[1])


def piggyback_slugs(state_flags, manifest, today, min_age_days, limit):
    # The flags this run retires in passing: the oldest eligible ones, at most `limit`.
    return [slug for slug, _ in candidates(state_flags, manifest, today, min_age_days)][:max(0, int(limit))]


def retirement_block(slugs):
    # The text added to a Build Run's task so the coder retires these flags in the same change. Empty for none.
    if not slugs:
        return ""
    lines = "\n".join(f"retire-flag: {s}" for s in slugs)
    return ("\n\nAlso in this change, retire the feature flag(s) below. Each has done its job: its change was released and a later release has "
            "come after it. Retire it so users notice no difference: remove the check of the flag and keep the behaviour it guarded, always on; "
            "remove its entry from `flags.json`; delete the tests that assert the flag-off behaviour and keep the tests of the behaviour itself; "
            "leave no code mentioning the slug (a comment may). Touch no other flag. Keep this separate from the main change (its own commit), "
            "and add no flag for it.\n" + lines)


def retirement_note(slugs):
    # What the tester and reviewer are told about the retired flags (added to the spec they check against).
    if not slugs:
        return ""
    return ("\n\nThis change also retires the feature flag(s) " + ", ".join(f"`{s}`" for s in slugs) + ", so the behaviour each guarded is now simply on "
            "for everyone. Check that it still works for an ordinary visitor with no Preview Token, exactly as it did when released, and that "
            "nothing else changed. The task carries `retire-flag: <slug>` lines for them.\n" + "\n".join(f"retire-flag: {s}" for s in slugs))


def app_flags(owner, app, pat):
    # (state flags from the App State issue, flags.json slugs at main), or (None, None) if either cannot be read.
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
    # The proven flags that ride along with a run, and {slug: story number} for the flags the State issue knows: none picked for a first build or an
    # automatic retry (`eligible` is false). A task that names flags itself (`retire-flag:` lines, from an owner's Intake) retires those too. Only
    # flags still in the manifest at the run's base count. A failed lookup never stops the run.
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
