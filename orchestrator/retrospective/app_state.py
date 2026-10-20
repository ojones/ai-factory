# Where each Managed App stands, kept in GitHub issues the Orchestrator maintains.
#
# - The **App State issue** (label `factory-state`) in each Managed App's repo: its recent Build Runs and every flag
#   a Build Run released, with the flag's last known state. This is how a person, or the next Build Run, learns
#   "what is in flight, what is released" without reading logs. It is an issue, not a file on `main`: a commit
#   would redeploy the app, race the release step, and break "only the coder's work reaches main".
# - The **registry issue** (label `factory-registry`) in ai-factory: one row per Managed App, linking each State issue.
#
# Each body carries its data as JSON in an HTML comment, so a rewrite never has to parse the tables. `finalize`
# calls `update_state_issue` and `update_registry` after every Build Run, best effort: a failure here never changes
# a run's outcome. The rendering functions are pure and unit-tested.
import json
import os
import re
import tempfile

from shared import app_state_record, outcomes
from shared.shell import sh

MAX_RUNS = 12


def cell(x):
    return str(x if x is not None else "").replace("|", "\\|").replace("\n", " ").strip()[:120]


def day(d):
    return (d.get("finished_at") or d.get("started_at") or "")[:10]


def story_link(flag):
    # A link to the issue a flag came from, built from the run URL's repository (the story lives in the Factory repo), or '-'.
    m = re.match(r"(https://github\.com/[^/]+/[^/]+)/actions/", flag.get("run_url") or "")
    return f"[#{flag['issue']}]({m.group(1)}/issues/{flag['issue']})" if m and flag.get("issue") else "-"


def render_state(prev_body, d):
    # The App State issue body after this run. `d` is the Build Run Report.
    data = app_state_record.load(prev_body)
    runs = data.get("runs", [])
    runs.append({"date": day(d), "outcome": d.get("outcome"), "kind": d.get("build_kind") or "", "run_url": d.get("run_url") or "",
                 "cost": round(d.get("spent_usd") or 0, 2), "rounds": d.get("review_passes") or 0,
                 "released": (d.get("release") or {}).get("released") or []})
    runs = runs[-MAX_RUNS:]
    flags = {f["key"]: f for f in data.get("flags", [])}
    off = d.get("outcome") == "watchdog_disabled"
    for key in (d.get("release") or {}).get("released") or []:
        flags[key] = {"key": key, "date": day(d), "run_url": d.get("run_url") or "", "issue": d.get("issue_number"),
                      "state": "switched off by the watchdog" if off else "released"}
    # A flagged change that was pushed and never released is a dark feature: it is listed (so a person can see it), and never taken for a
    # released flag. Once it is released at last, the release above replaces the entry.
    if d.get("flags") and d.get("commits") and d.get("outcome") not in outcomes.OK + ("refused", outcomes.PROVIDER_BLOCKED) and not off:
        for slug in d["flags"]:
            key = f"{d.get('app')}.feature.{slug}"
            if key not in flags or str(flags[key].get("state", "")).startswith("dark"):
                flags[key] = {"key": key, "date": day(d), "run_url": d.get("run_url") or "", "issue": d.get("issue_number"),
                              "state": "dark (failed its checks; fixed forward behind its flag)"}
    data = {"runs": runs, "flags": sorted(flags.values(), key=lambda f: f["date"])}
    last = runs[-1]
    lines = [f"# {d.get('app')}: Factory state", "",
             "Kept up to date by the Orchestrator after every Build Run. Edit nothing here by hand; it is rewritten.", "",
             f"**Last Build Run**: {cell(last['outcome'])} on {cell(last['date'])} ([run]({last['run_url']}))", "",
             "## Recent Build Runs", "", "| Date | Outcome | Kind | Rounds | Cost | Released |", "|---|---|---|---|---|---|"]
    lines += [f"| {cell(r['date'])} | {cell(r['outcome'])} | {cell(r['kind'])} | {r['rounds']} | ${r['cost']:.2f} | "
              f"{cell(', '.join(k.split('.feature.')[-1] for k in r['released']) or '-')} |" for r in reversed(runs)]
    lines += ["", "## Flags from Build Runs", "",
              "The state is as of the release (or the watchdog); the owner may have changed a flag in GrowthBook since. A dark flag was never released: its story is labelled `dark-broken` once its retries are used up.", ""]
    if data["flags"]:
        lines += ["| Flag | Date | State | Story |", "|---|---|---|---|"]
        lines += [f"| `{cell(f['key'])}` | {cell(f['date'])} | {cell(f['state'])} | {story_link(f)} |" for f in reversed(data["flags"])]
    else:
        lines.append("None yet.")
    return "\n".join(lines) + "\n\n" + app_state_record.dump(data) + "\n"


def render_registry(prev_body, d, state_url):
    # The registry body after this run: one row per app, keyed by app name.
    data = app_state_record.load(prev_body)
    apps = data.get("apps", {})
    row = apps.get(d.get("app"), {"runs": 0, "ok": 0})
    row.update(outcome=d.get("outcome"), date=day(d), run_url=d.get("run_url") or "", state_url=state_url or row.get("state_url", ""),
               runs=row["runs"] + 1, ok=row["ok"] + (1 if d.get("outcome") in outcomes.OK else 0))
    apps[d.get("app")] = row
    data = {"apps": dict(sorted(apps.items()))}
    lines = ["# Managed Apps", "", "One row per app, kept up to date by the Orchestrator after every Build Run.", "",
             "| App | Last outcome | Date | Runs (OK) | State |", "|---|---|---|---|---|"]
    for app, r in data["apps"].items():
        state = f"[state]({r['state_url']})" if r.get("state_url", "").startswith("https://") else "-"
        lines.append(f"| {cell(app)} | [{cell(r['outcome'])}]({r['run_url']}) | {cell(r['date'])} | {r['runs']} ({r['ok']}) | {state} |")
    return "\n".join(lines) + "\n\n" + app_state_record.dump(data) + "\n"


def update_state_issues(d, factory_repo, pat, factory_token):
    # Rewrite the app's State issue and ai-factory's registry issue after a run (best effort).
    try:
        owner, app = factory_repo.split("/")[0], d["app"]
        app_repo = f"{owner}/{app}"

        def gh(args, token):
            return sh(["gh", *args], env={**os.environ, "GH_TOKEN": token}, check=False).stdout

        def upsert(repo, token, label, title, color, render):
            found = json.loads(gh(["issue", "list", "--repo", repo, "--label", label, "--state", "open",
                                   "--json", "number,body,url"], token) or "[]")
            prev = found[0]["body"] if found else ""
            body = render(prev)
            if found:
                number, url = found[0]["number"], found[0]["url"]
                with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                    f.write(body)
                gh(["issue", "edit", str(number), "--repo", repo, "--body-file", f.name], token)
                return url
            gh(["label", "create", label, "--repo", repo, "--color", color, "--description", "Maintained by the Orchestrator"], token)
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                f.write(body)
            made = gh(["issue", "create", "--repo", repo, "--label", label, "--title", title, "--body-file", f.name], token)
            m = re.search(r"https://\S+/issues/(\d+)", made)
            if m:
                gh(["issue", "pin", m.group(1), "--repo", repo], token)  # best effort; not every plan allows it
            return m.group(0) if m else ""

        state_url = upsert(app_repo, pat, app_state_record.STATE_LABEL, "Factory: app state", "5319e7", lambda prev: render_state(prev, d))
        upsert(factory_repo, factory_token, app_state_record.REGISTRY_LABEL, "Factory: Managed Apps", "5319e7",
               lambda prev: render_registry(prev, d, state_url))
    except Exception as e:  # noqa: BLE001
        print(f"could not update the state issues: {type(e).__name__}", flush=True)
