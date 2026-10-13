#!/usr/bin/env python3
"""Find Fly apps nobody owns: machines that bill while nothing in the Factory knows about them.

A Fly app is owned if it is Factory infrastructure (`limits.fly_infra_apps` in agents/profiles.yml, plus GrowthBook) or a
Managed App: a repo in the Factory owner's account whose description carries the `Intake: <factory repo>#<n>` marker App
Staging writes. Anything else is an orphan, for example after a failed teardown or an App Staging run that stopped between
creating the Fly app and the repo. Nothing is deleted here: the audit keeps one open `fly-orphans` issue in ai-factory,
updated when the list changes and closed when it is empty, and the person decides (teardown.yml removes a Managed App).

Env: FLY_API_TOKEN, FLY_ORG (the Fly organization slug, default `personal`), FACTORY_PAT (read repos), FACTORY_GH_TOKEN
(the Actions token, used for the issue), GITHUB_REPOSITORY.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import update_intake  # noqa: E402

LABEL = "fly-orphans"
ALWAYS_OWNED = ("ai-factory-growthbook",)


def orphans(fly_apps, infra, owned_repo):
    """The Fly apps (name, machine count) that are neither infrastructure nor have a Managed App repo. `owned_repo(name)` says
    whether a repo with the Factory's marker exists for it."""
    keep = set(ALWAYS_OWNED) | set(infra)
    return sorted((a for a in fly_apps if a["name"] not in keep and not owned_repo(a["name"])), key=lambda a: a["name"])


def render(found, org):
    if not found:
        return "No Fly app without an owner."
    lines = [f"These apps in the Fly organization `{org}` are neither Factory infrastructure nor a Managed App the Factory created. "
             "If they are not yours, they may be billing for machines that nothing will stop.", "",
             "| Fly app | Machines |", "|---|---|"]
    lines += [f"| `{a['name']}` | {a.get('machines', '?')} |" for a in found]
    lines += ["", "For a Managed App whose teardown failed, run the Teardown workflow. For anything else, check it in Fly "
                  "(`fly apps destroy <name>`) once you are sure. This audit never deletes anything."]
    return "\n".join(lines)


def list_fly_apps(org, token):
    status, r = b.http("GET", f"https://api.machines.dev/v1/apps?org_slug={org}", token, timeout=30)
    if status != 200 or not isinstance(r, dict) or "apps" not in r:
        raise RuntimeError(f"could not list Fly apps for {org!r}: HTTP {status}")
    return [{"name": a["name"], "machines": a.get("machine_count")} for a in r["apps"] if a.get("name")]


def idle_days(last_push_iso, now=None):
    """Whole days since an ISO timestamp, or None if it cannot be read."""
    import time
    try:
        then = time.mktime(time.strptime(last_push_iso[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (ValueError, TypeError):
        return None
    return int(((now or time.time()) - then) // 86400)


def idle_report(rows):
    """A markdown table of [(app, days idle or None)], longest idle first. Report only: nothing is retired automatically."""
    lines = ["### Managed Apps by days since the last push", "", "| App | Days idle |", "|---|---|"]
    for app, days in sorted(rows, key=lambda r: -(r[1] if r[1] is not None else -1)):
        lines.append(f"| `{app}` | {days if days is not None else '?'} |")
    lines += ["", "Nothing is retired automatically. Run the Teardown workflow for an app you no longer need."]
    return "\n".join(lines)


def main():
    repo, org = os.environ["GITHUB_REPOSITORY"], os.environ.get("FLY_ORG") or "personal"
    owner, pat, token = repo.split("/")[0], os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    infra = (b.load_config().get("limits") or {}).get("fly_infra_apps") or []

    def owned_repo(name):
        out = b.sh(["gh", "api", f"repos/{owner}/{name}", "--jq", ".description"], env={**os.environ, "GH_TOKEN": pat}, check=False)
        return out.returncode == 0 and update_intake.is_factory_repo(out.stdout.strip(), repo)

    try:  # the idle-app report goes in the run summary; it never fails the audit
        import production_feedback as pf
        rows = []
        for app in pf.managed_apps(repo, token):
            pushed = b.sh(["gh", "api", f"repos/{owner}/{app}", "--jq", ".pushed_at"], env={**os.environ, "GH_TOKEN": pat}, check=False).stdout.strip()
            rows.append((app, idle_days(pushed)))
        report = idle_report(rows)
        print(report)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a").write(report + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"idle report failed: {type(e).__name__}: {e}")
    found = orphans(list_fly_apps(org, os.environ["FLY_API_TOKEN"]), infra, owned_repo)
    env = {**os.environ, "GH_TOKEN": token}
    update_intake.ensure_label(repo, LABEL, token, "b60205", "Fly apps nobody owns")
    open_issues = json.loads(b.sh(["gh", "issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--json", "number,body"],
                                  env=env).stdout or "[]")
    body = render(found, org)
    print(body)
    if not found:
        for i in open_issues:
            b.sh(["gh", "issue", "close", str(i["number"]), "--repo", repo, "--comment", "No orphaned Fly apps remain."], env=env, check=False)
    elif not open_issues:
        b.sh(["gh", "issue", "create", "--repo", repo, "--label", LABEL, "--label", "needs-human", "--title",
              "Fly apps nobody owns", "--body", body], env=env, check=False)
    elif (open_issues[0].get("body") or "").strip() != body.strip():
        b.sh(["gh", "issue", "edit", str(open_issues[0]["number"]), "--repo", repo, "--body", body], env=env, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
