"""Where each Managed App stands, kept in GitHub issues the Orchestrator maintains.

- The **App State issue** (label `factory-state`) in each Managed App's repo: its recent Build Runs and every flag
  a Build Run released, with the flag's last known state. This is how a person, or the next Build Run, learns
  "what is in flight, what is released" without reading logs. It is an issue, not a file on `main`: a commit
  would redeploy the app, race the release step, and break "only the coder's work reaches main".
- The **registry issue** (label `factory-registry`) in ai-factory: one row per Managed App, linking each State issue.

Each body carries its data as JSON in an HTML comment, so a rewrite never has to parse the tables. `finalize`
calls `update_state_issue` and `update_registry` after every Build Run, best effort: a failure here never changes
a run's outcome. The rendering functions are pure and unit-tested.
"""
import json
import re

STATE_LABEL = "factory-state"
REGISTRY_LABEL = "factory-registry"
MAX_RUNS = 12
DATA_RE = re.compile(r"<!-- factory-data:(.*?) -->", re.S)
OK = ("released", "nothing_to_release", "planned")


def cell(x):
    return str(x if x is not None else "").replace("|", "\\|").replace("\n", " ").strip()[:120]


def load(body):
    m = DATA_RE.search(body or "")
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


def dump(data):
    # "--" inside an HTML comment could end it early; as a JSON escape it survives a round trip unchanged.
    return "<!-- factory-data:" + json.dumps(data, separators=(",", ":")).replace("--", "\\u002d\\u002d") + " -->"


def day(d):
    return (d.get("finished_at") or d.get("started_at") or "")[:10]


def render_state(prev_body, d):
    """The App State issue body after this run. `d` is the Build Run Report."""
    data = load(prev_body)
    runs = data.get("runs", [])
    runs.append({"date": day(d), "outcome": d.get("outcome"), "kind": d.get("build_kind") or "", "run_url": d.get("run_url") or "",
                 "cost": round(d.get("spent_usd") or 0, 2), "rounds": d.get("review_passes") or 0,
                 "released": (d.get("release") or {}).get("released") or []})
    runs = runs[-MAX_RUNS:]
    flags = {f["key"]: f for f in data.get("flags", [])}
    off = d.get("outcome") == "watchdog_disabled"
    for key in (d.get("release") or {}).get("released") or []:
        flags[key] = {"key": key, "date": day(d), "run_url": d.get("run_url") or "",
                      "state": "switched off by the watchdog" if off else "released"}
    data = {"runs": runs, "flags": sorted(flags.values(), key=lambda f: f["date"])}
    last = runs[-1]
    lines = [f"# {d.get('app')}: Factory state", "",
             "Kept up to date by the Orchestrator after every Build Run. Edit nothing here by hand; it is rewritten.", "",
             f"**Last Build Run**: {cell(last['outcome'])} on {cell(last['date'])} ([run]({last['run_url']}))", "",
             "## Recent Build Runs", "", "| Date | Outcome | Kind | Rounds | Cost | Released |", "|---|---|---|---|---|---|"]
    lines += [f"| {cell(r['date'])} | {cell(r['outcome'])} | {cell(r['kind'])} | {r['rounds']} | ${r['cost']:.2f} | "
              f"{cell(', '.join(k.split('.feature.')[-1] for k in r['released']) or '-')} |" for r in reversed(runs)]
    lines += ["", "## Flags released by Build Runs", "",
              "The state is as of the release (or the watchdog); the owner may have changed a flag in GrowthBook since.", ""]
    if data["flags"]:
        lines += ["| Flag | Date | State |", "|---|---|---|"]
        lines += [f"| `{cell(f['key'])}` | {cell(f['date'])} | {cell(f['state'])} |" for f in reversed(data["flags"])]
    else:
        lines.append("None yet.")
    return "\n".join(lines) + "\n\n" + dump(data) + "\n"


def render_registry(prev_body, d, state_url):
    """The registry body after this run: one row per app, keyed by app name."""
    data = load(prev_body)
    apps = data.get("apps", {})
    row = apps.get(d.get("app"), {"runs": 0, "ok": 0})
    row.update(outcome=d.get("outcome"), date=day(d), run_url=d.get("run_url") or "", state_url=state_url or row.get("state_url", ""),
               runs=row["runs"] + 1, ok=row["ok"] + (1 if d.get("outcome") in OK else 0))
    apps[d.get("app")] = row
    data = {"apps": dict(sorted(apps.items()))}
    lines = ["# Managed Apps", "", "One row per app, kept up to date by the Orchestrator after every Build Run.", "",
             "| App | Last outcome | Date | Runs (OK) | State |", "|---|---|---|---|---|"]
    for app, r in data["apps"].items():
        state = f"[state]({r['state_url']})" if r.get("state_url", "").startswith("https://") else "-"
        lines.append(f"| {cell(app)} | [{cell(r['outcome'])}]({r['run_url']}) | {cell(r['date'])} | {r['runs']} ({r['ok']}) | {state} |")
    return "\n".join(lines) + "\n\n" + dump(data) + "\n"
