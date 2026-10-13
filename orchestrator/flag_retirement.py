#!/usr/bin/env python3
"""Flag retirement: a feature flag is short-lived, so once a change is proven in production its flag is removed, by itself.

A flag exists for one job: to stage a change dark and release it when it is safe (STANDARDS-FEATURE-FLAGS.md). Nobody uses it for
anything else, so once a *later* Build Run has also released something, the earlier release has been replaced by a newer one and its
flag has done its job. This daily pass finds those flags and files one Update Intake per flag that removes the check, keeps the
behaviour always on, and removes the flag's line in `flags.json`; the Build Run then archives the flag in GrowthBook. Users see no
change. The owner's standing approval is the standard; nobody reviews a retirement.

A flag is a candidate when all of these hold, read from the app's State issue and `flags.json`:
  - it is in `flags.json` and the State issue records it as `released` (not one the watchdog switched off: that one is dead, and the fix
    request replaces it with a new flag);
  - a later Build Run of the app also released a flag (its run id is higher);
  - it was released on an earlier day than today (a soak of at least a day, so the production-feedback scans have looked at it).
The newest release therefore always keeps its flag, and a run that ended `nothing_to_release` retires nothing.

  python3 flag_retirement.py       Env: FACTORY_PAT, FACTORY_GH_TOKEN, GITHUB_REPOSITORY, optional FLAG_RETIRE_MIN_AGE_DAYS
Switch and limits: `limits.flag_retirement` in agents/profiles.yml. One open retirement per app at a time, oldest first.
"""
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
import production_feedback as pf  # noqa: E402

LABEL = "flag-retirement"
DEFAULTS = {"enabled": True, "min_age_days": 1, "max_per_app_per_day": 2}
RUN_ID_RE = re.compile(r"/runs/(\d+)")


# --- pure logic (unit-tested) -------------------------------------------------


def run_id(entry):
    m = RUN_ID_RE.search(entry.get("run_url") or "")
    return int(m.group(1)) if m else 0


def slug_of(key):
    return key.split(".feature.")[-1]


def age_days(date, today):
    """Whole days between two YYYY-MM-DD strings, or None if either cannot be read."""
    try:
        a, b_ = time.strptime(date, "%Y-%m-%d"), time.strptime(today, "%Y-%m-%d")
        return int((time.mktime(b_) - time.mktime(a)) // 86400)
    except (ValueError, TypeError):
        return None


def candidates(state_flags, manifest, today, min_age_days):
    """The flags to retire, oldest release first: [(slug, run id)]. See the module docstring for the rules."""
    released = [f for f in state_flags if f.get("state") == "released"]
    newest = max((run_id(f) for f in released), default=0)
    out = []
    for f in released:
        slug, rid, age = slug_of(f["key"]), run_id(f), age_days(f.get("date", ""), today)
        if slug in manifest and rid and rid < newest and age is not None and age >= min_age_days:
            out.append((slug, rid))
    return sorted(set(out), key=lambda c: c[1])


def marker(slug, rid):
    return f"[retire {slug}@{rid}]"


def should_file(cands, filed_titles, open_for_app, made_today, max_per_day):
    """The first candidate that has not been filed before, or None. Nothing while one is open or today's limit is reached."""
    if open_for_app or made_today >= max_per_day:
        return None
    for slug, rid in cands:
        if not any(marker(slug, rid) in t for t in filed_titles):
            return slug, rid
    return None


def retirement_request(app, slug):
    return (f"retire-flag: {slug}\n\n"
            f"The feature flag `{slug}` has done its job: its change was released, a later release has come after it, and it has been in production "
            "long enough. Retire it so users notice no difference:\n"
            f"- remove the check of `{slug}` (the `isFeatureEnabled(res, \"{slug}\")` call or the wrapper around the change) and keep the behaviour it "
            "guarded, always on;\n"
            f"- remove the `{slug}` entry from `flags.json`;\n"
            "- delete the tests that assert the flag-off behaviour (the route answering 404 or the control being hidden), and keep the tests of the "
            "behaviour itself;\n"
            f"- no code may mention `{slug}` afterwards (a comment may).\n\n"
            "This is internal: it needs no feature flag of its own, and you add no behaviour. Do not touch other flags.")


# --- GitHub (not unit-tested) -------------------------------------------------


def app_flags(owner, app, pat):
    """(state flags from the App State issue, flags.json slugs at main), or (None, None) if either cannot be read."""
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


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, token, pat = repo.split("/")[0], os.environ["FACTORY_GH_TOKEN"], os.environ["FACTORY_PAT"]
    cfg = {**DEFAULTS, **((b.load_config().get("limits") or {}).get("flag_retirement") or {})}
    if not cfg["enabled"]:
        b.log("flag retirement is off")
        return 0
    min_age = int(os.environ.get("FLAG_RETIRE_MIN_AGE_DAYS") or cfg["min_age_days"])
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for app in pf.managed_apps(repo, token):
        try:
            state_flags, manifest = app_flags(owner, app, pat)
            if state_flags is None:
                b.log(f"{app}: no State issue or flags.json to read")
                continue
            cands = candidates(state_flags, manifest, today, min_age)
            every = pf.intakes_with(repo, token, app, LABEL, "all")
            open_now = pf.intakes_with(repo, token, app, LABEL, "open")
            made_today = sum(1 for i in every if i["createdAt"][:10] == today)
            pick = should_file(cands, [i["title"] for i in every], open_now, made_today, int(cfg["max_per_app_per_day"]))
            if not pick:
                b.log(f"{app}: {len(cands)} candidate(s); nothing to file")
                continue
            slug, rid = pick
            n = pf.file_intake(repo, token, pat, app, f"{app}: retire flag {slug} {marker(slug, rid)}", retirement_request(app, slug), LABEL,
                               "Filed and started by the Orchestrator to retire a proven feature flag",
                               "Started automatically: the flag is proven and a later release has come after it. The planner runs first.")
            b.log(f"{app}: retirement of {slug} filed as #{n}")
        except Exception as e:  # noqa: BLE001 - one app's failure never stops the others
            b.log(f"{app}: flag retirement failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
