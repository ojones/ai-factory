#!/usr/bin/env python3
"""Maintenance: dependency and base-image updates reach the Managed Apps through the same gate as any other change.

Each app carries `.github/dependabot.yml` (from the Starter Template), so Dependabot watches its npm packages, its Docker base image
and its GitHub Actions every day, and opens a pull request for each update or security fix. Dependabot only detects here: nothing
merges those pull requests. This daily pass reads each app's open Dependabot pull requests and, when there are updates an Agent can
apply (npm packages and the Docker image), files one Update Intake that lists them and starts it. The planner, coder, tester and
reviewer apply them, and the change ships like any other; a dependency bump needs no flag (users see no difference).
Dependabot closes its own pull requests once the dependency is updated. Updates to GitHub Actions live in `.github/`, which Agents
may not edit, so they are only reported.

  python3 maintenance.py        Env: FACTORY_PAT, FACTORY_GH_TOKEN, GITHUB_REPOSITORY.   Switch: limits.maintenance.enabled
One Intake per app and set of updates (a failed one is not refiled; its fix request is), one open at a time per app.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import production_feedback as pf  # noqa: E402

LABEL = "maintenance"
ECOSYSTEMS = (("npm_and_yarn", "npm"), ("docker", "docker"), ("github_actions", "actions"))
APPLICABLE = ("npm", "docker")


# --- pure logic (unit-tested) -------------------------------------------------


def ecosystem(pr):
    """npm | docker | actions | other, from Dependabot's branch name (dependabot/<ecosystem>/...)."""
    ref = pr.get("headRefName") or ""
    for key, name in ECOSYSTEMS:
        if ref.startswith(f"dependabot/{key}/"):
            return name
    return "other"


def is_security(pr):
    return any("security" in (l.get("name") or "").lower() for l in pr.get("labels") or [])


def split_prs(prs):
    """(applicable, only reported): the pull requests an Agent can apply, and the ones it cannot (Actions, anything unknown)."""
    mine = [p for p in prs if ecosystem(p) in APPLICABLE]
    return mine, [p for p in prs if p not in mine]


def update_key(prs):
    """A short stable key for this set of updates (their titles name the versions), so the same set is filed once."""
    return hashlib.sha1("\n".join(sorted(p["title"] for p in prs)).encode()).hexdigest()[:8]


def should_file(applicable, key, filed_titles, open_for_app):
    return bool(applicable) and not open_for_app and not any(f"[maint {key}]" in t for t in filed_titles)


def clean_title(title):
    return re.sub(r"\s+", " ", title or "").strip()[:160]


def maintenance_request(app, applicable, reported):
    lines = []
    for p in sorted(applicable, key=lambda p: (not is_security(p), p["number"])):
        lines.append(f"- {'**security** ' if is_security(p) else ''}{clean_title(p['title'])} ({ecosystem(p)}; Dependabot PR {p['url']})")
    parts = ["Dependabot found these updates for the app's dependencies. Apply them all in this change:", "", *lines, "",
             "How: update `package.json` and `package-lock.json` (run `npm install`) for the npm packages; change the `FROM` lines in "
             "the `Dockerfile` (both stages, keep the digest pin) for a Docker base image update. If an update is a major version, read "
             "its release notes and fix what breaks. Then run `npm run format`, then `npm run check` and `npm test`, and make sure the "
             "app still builds and its health route answers. If one update cannot be applied without breaking the app, leave that "
             "one out and say which and why in the commit message.",
             "", "This is maintenance that users cannot see, so it needs no feature flag; do not add behaviour."]
    if reported:
        parts += ["", "Not part of this change (they edit `.github/`, which Agents may not change): " + "; ".join(clean_title(p["title"]) for p in reported)]
    return "\n".join(parts)


# --- GitHub (not unit-tested) -------------------------------------------------


def dependabot_prs(owner, app, pat):
    out = b.sh(["gh", "pr", "list", "--repo", f"{owner}/{app}", "--author", "app/dependabot", "--state", "open", "--limit", "50",
                "--json", "number,title,url,headRefName,labels"], env={**os.environ, "GH_TOKEN": pat}, check=False).stdout
    return json.loads(out or "[]")


def enable_security_updates(owner, app, pat):
    """Dependabot alerts and security updates on for the app's repo (idempotent; best effort, since the PAT may lack the scope)."""
    env = {**os.environ, "GH_TOKEN": pat}
    for endpoint in ("vulnerability-alerts", "automated-security-fixes"):
        p = b.sh(["gh", "api", "-X", "PUT", f"repos/{owner}/{app}/{endpoint}"], env=env, check=False)
        if p.returncode != 0:
            b.log(f"{app}: could not enable {endpoint}: {(p.stderr or p.stdout).strip()[:160]}")


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, token, pat = repo.split("/")[0], os.environ["FACTORY_GH_TOKEN"], os.environ["FACTORY_PAT"]
    if not ((b.load_config().get("limits") or {}).get("maintenance") or {}).get("enabled", True):
        b.log("maintenance is off")
        return 0
    for app in pf.managed_apps(repo, token):
        try:
            enable_security_updates(owner, app, pat)
            applicable, reported = split_prs(dependabot_prs(owner, app, pat))
            key = update_key(applicable) if applicable else ""
            titles = [i["title"] for i in pf.intakes_with(repo, token, app, LABEL, "all")]
            open_now = pf.intakes_with(repo, token, app, LABEL, "open")
            if not should_file(applicable, key, titles, open_now):
                b.log(f"{app}: {len(applicable)} applicable update(s); nothing to file")
                continue
            n = pf.file_intake(repo, token, pat, app, f"{app}: dependency updates [maint {key}]", maintenance_request(app, applicable, reported), LABEL,
                               "Filed and started by the Orchestrator for dependency and base-image updates",
                               "Started automatically from Dependabot's pull requests. The planner runs first.")
            b.log(f"{app}: maintenance filed as #{n} ({len(applicable)} update(s))")
        except Exception as e:  # noqa: BLE001 - one app's failure never stops the others
            b.log(f"{app}: maintenance failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
