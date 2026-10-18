#!/usr/bin/env python3
# Switch one Managed App flag on or off in production by hand (the owner's lever; run by .github/workflows/flag-set.yml).
#
# The release step creates flags and the watchdog switches them off. This is the same call for a person: turning a released flag
# off is the rollback, and turning one on is for a test such as the production-feedback check. It changes the `production`
# environment's `enabled` switch of one existing flag and reads it back; it never creates a flag or edits rules.
#
#   python3 flag_set.py <app> <flag-slug> on|off        Env: GROWTHBOOK_ADMIN_PAT
# Exit 0 if the read-back shows the requested state, 1 otherwise, 2 for bad input.
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402


def feature_key(app, slug):
    # The GrowthBook key, or None if the app or slug is not a valid name (so nothing odd is ever put in a URL).
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", app or "") or not b.SLUG_RE.fullmatch(slug or ""):
        return None
    return f"{app}.feature.{slug}"


def main(argv):
    if len(argv) != 4 or argv[3] not in ("on", "off") or not feature_key(argv[1], argv[2]):
        print("usage: flag_set.py <app> <flag-slug> on|off", file=sys.stderr)
        return 2
    key, want = feature_key(argv[1], argv[2]), argv[3] == "on"
    token = os.environ["GROWTHBOOK_ADMIN_PAT"]
    status, r = b.http("GET", f"{b.GROWTHBOOK_API}/features/{key}", token)
    if status != 200:
        print(f"{key}: no such flag (HTTP {status}); nothing changed", file=sys.stderr)
        return 1
    prod = (((r.get("feature") or r) if isinstance(r, dict) else {}).get("environments") or {}).get("production") or {}
    # The API wants the environment's rules with the switch (the watchdog sends rules too); send the current ones back unchanged.
    code, reply = b.http("POST", f"{b.GROWTHBOOK_API}/features/{key}", token,
                         {"environments": {"production": {"enabled": want, "rules": prod.get("rules") or []}}})
    if code != 200:
        print(f"{key}: the update answered HTTP {code}: {str(reply)[:300]}", file=sys.stderr)
    status, r = b.http("GET", f"{b.GROWTHBOOK_API}/features/{key}", token)
    now = (((r.get("feature") or r) if isinstance(r, dict) else {}).get("environments") or {}).get("production", {}).get("enabled")
    print(f"{key}: production is now {'on' if now else 'off'} (asked for {argv[3]})")
    return 0 if status == 200 and now is want else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
