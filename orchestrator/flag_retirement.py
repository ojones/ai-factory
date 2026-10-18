#!/usr/bin/env python3
# Flag retirement: a feature flag is short-lived, so once a change is proven in production its flag is removed, by itself.
#
# A flag exists for one job: to stage a change dark and release it when it is safe (STANDARDS-FEATURE-FLAGS.md). Nobody uses it for
# anything else, so once a *later* Build Run has also released something, the earlier release has been replaced by a newer one and its
# flag has done its job. A retirement is never a run of its own (that would spend a planner, reviewer, tester, CI and a deploy on a change
# that only deletes a check): the next Update Intake for the same app carries it. At the start of that Build Run the Orchestrator picks
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
# by the story's automatic retries (`fix_request_max_attempts`). Only after those are used up (the story is labelled `needs-human` and
# `dark-broken`) and a person adds the label `approve-retire` to the story is it removed: `approve` files an Update Intake that deletes the
# flag's check, the code it guarded, its tests and its line in `flags.json`, and starts it. Nothing removes a dark feature on its own.
#
# Limits: `limits.flag_retirement` in agents/profiles.yml (`piggyback_max` flags per run, default 5, so a backlog clears; `min_age_days`).
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import appstate  # noqa: E402
import build_run as b  # noqa: E402

RUN_ID_RE = re.compile(r"/runs/(\d+)")


# --- pure logic (unit-tested) -------------------------------------------------


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


APPROVE = "approve-retire"


def dark_removal_target(labels):
    # (app, slug, None) when a person's approval can retire this story's dark feature, else (None, None, why not).
    labels = set(labels)
    if "update-intake" not in labels:
        return None, None, "this is not an Update Intake story"
    if b.DARK_BROKEN not in labels:
        return None, None, f"the story has no broken dark feature (it is not labelled `{b.DARK_BROKEN}`)"
    if "needs-human" not in labels:
        return None, None, "the automatic retries are not used up yet (the story is not labelled `needs-human`); they fix it forward first"
    slugs = sorted(l[5:] for l in labels if l.startswith("flag:"))
    apps = sorted(l[4:] for l in labels if l.startswith("app:"))
    if len(slugs) != 1 or len(apps) != 1:
        return None, None, "the story must name exactly one flag (`flag:<slug>`) and one app (`app:<name>`)"
    return apps[0], slugs[0], None


def dark_removal_task(slug, story):
    # The request an approved retirement files: remove the feature, since it never released. Users see no difference.
    return (f"Remove the dark feature behind the flag `{slug}`. It was built in #{story}, never passed its checks and was never released, "
            "so no user has ever seen it and its flag is off. A person has approved removing it.\n\n"
            f"Delete the check of `{slug}`, the code it guarded (routes, UI, helpers, migrations that only it used) and the tests that "
            f"exercise it; remove its entry from `flags.json`. Leave no code that mentions the slug (a comment may). Touch no other flag and "
            "change nothing else: the app must behave exactly as it does today.")


def approve(repo, pat, number):
    # The story #number got the label `approve-retire`: file the removal as an Update Intake and start it. Returns 0 either way (a refusal
    # is a comment on the story, not a failed workflow).
    import update_intake as ui
    env = {**os.environ, "GH_TOKEN": pat}
    story = json.loads(b.sh(["gh", "issue", "view", str(number), "--repo", repo, "--json", "labels,title"], env=env).stdout)
    labels = [l["name"] for l in story["labels"]]
    app, slug, why = dark_removal_target(labels)
    b.sh(["gh", "issue", "edit", str(number), "--repo", repo, "--remove-label", APPROVE], env=env, check=False)
    if why:
        b.sh(["gh", "issue", "comment", str(number), "--repo", repo, "--body", f"**Retirement not started:** {why}."], env=env, check=False)
        return 0
    for name, color, desc in ((ui.FORM_LABEL, "1d76db", "A change request for an existing Managed App"), (ui.GO, "0e8a16", "Start this change now"),
                              (f"app:{app}", "1d76db", f"Issues about the Managed App {app}")):
        ui.ensure_label(repo, name, pat, color, desc)
    body = (f"### App name\n\n{app}\n\n### What should change?\n\n{dark_removal_task(slug, number)}\n\n### Cost cap override (USD)\n\n_No response_\n")
    out = b.sh(["gh", "issue", "create", "--repo", repo, "--title", f"{app}: Remove dark feature {slug}", "--body", body,
                "--label", f"{ui.FORM_LABEL},app:{app}"], env=env).stdout
    made = re.search(r"/issues/(\d+)", out)
    if not made:
        return 0
    b.sh(["gh", "issue", "edit", made.group(1), "--repo", repo, "--add-label", ui.GO], env=env)  # the PAT: the Actions token would not start the workflow
    b.sh(["gh", "issue", "comment", str(number), "--repo", repo, "--body",
          f"**Retirement approved.** The dark feature `{slug}` is being removed by #{made.group(1)}. This story is closed; the removal "
          "leaves the app exactly as it is today."], env=env, check=False)
    b.sh(["gh", "issue", "close", str(number), "--repo", repo, "--reason", "not planned"], env=env, check=False)
    return 0


# --- GitHub (not unit-tested) -------------------------------------------------


def app_flags(owner, app, pat):
    # (state flags from the App State issue, flags.json slugs at main), or (None, None) if either cannot be read.
    env = {**os.environ, "GH_TOKEN": pat}
    out = b.sh(["gh", "issue", "list", "--repo", f"{owner}/{app}", "--label", appstate.STATE_LABEL, "--state", "open", "--json", "body"], env=env, check=False).stdout
    found = json.loads(out or "[]")
    if not found:
        return None, None
    manifest = b.sh(["gh", "api", f"repos/{owner}/{app}/contents/flags.json", "--jq", ".content"], env=env, check=False)
    if manifest.returncode != 0:
        return None, None
    try:
        slugs = b.manifest_slugs(base64.b64decode(manifest.stdout).decode())
    except ValueError:
        return None, None
    return appstate.load(found[0]["body"]).get("flags", []), slugs


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "approve":
        sys.exit(approve(os.environ["FACTORY_REPO"], os.environ["FACTORY_PAT"], int(sys.argv[2])))
    print("usage: flag_retirement.py approve <story issue number>", file=sys.stderr)
    sys.exit(2)
