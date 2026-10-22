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
    m = re.match(r"(https://github\.com/[^/]+/[^/]+)/actions/", flag.get("run_url") or "")
    return f"[#{flag['issue']}]({m.group(1)}/issues/{flag['issue']})" if m and flag.get("issue") else "-"


def run_entry(d):
    return {"date": day(d), "outcome": d.get("outcome"), "kind": d.get("build_kind") or "", "run_url": d.get("run_url") or "",
            "cost": round(d.get("spent_usd") or 0, 2), "rounds": d.get("review_passes") or 0, "released": (d.get("release") or {}).get("released") or []}


def flag_entry(d, key, state):
    return {"key": key, "date": day(d), "run_url": d.get("run_url") or "", "issue": d.get("issue_number"), "state": state}


def failed_flags_are_dark(d):
    gone_wrong = d.get("outcome") not in outcomes.OK + ("refused", outcomes.PROVIDER_BLOCKED)
    return bool(d.get("flags") and d.get("commits") and gone_wrong and d.get("outcome") != "watchdog_disabled")


def updated_flags(d, flags):
    off = d.get("outcome") == "watchdog_disabled"
    for key in (d.get("release") or {}).get("released") or []:
        flags[key] = flag_entry(d, key, "switched off by the watchdog" if off else "released")
    if failed_flags_are_dark(d):
        for slug in d["flags"]:
            key = f"{d.get('app')}.feature.{slug}"
            if key not in flags or str(flags[key].get("state", "")).startswith("dark"):
                flags[key] = flag_entry(d, key, "dark (failed its checks; fixed forward by a fix child)")
    return sorted(flags.values(), key=lambda f: f["date"])


def run_rows(runs):
    return [f"| {cell(r['date'])} | {cell(r['outcome'])} | {cell(r['kind'])} | {r['rounds']} | ${r['cost']:.2f} | "
            f"{cell(', '.join(k.split('.feature.')[-1] for k in r['released']) or '-')} |" for r in reversed(runs)]


def flag_rows(flags):
    if not flags:
        return ["None yet."]
    rows = [f"| `{cell(f['key'])}` | {cell(f['date'])} | {cell(f['state'])} | {story_link(f)} |" for f in reversed(flags)]
    return ["| Flag | Date | State | Story |", "|---|---|---|---|"] + rows


def render_state(prev_body, d):
    data = app_state_record.load(prev_body)
    runs = (data.get("runs", []) + [run_entry(d)])[-MAX_RUNS:]
    data = {"runs": runs, "flags": updated_flags(d, {f["key"]: f for f in data.get("flags", [])})}
    last = runs[-1]
    lines = [f"# {d.get('app')}: Factory state", "",
             "Kept up to date by the Orchestrator after every Build Run. Edit nothing here by hand; it is rewritten.", "",
             f"**Last Build Run**: {cell(last['outcome'])} on {cell(last['date'])} ([run]({last['run_url']}))", "",
             "## Recent Build Runs", "", "| Date | Outcome | Kind | Rounds | Cost | Released |", "|---|---|---|---|---|---|"]
    lines += run_rows(runs) + ["", "## Flags from Build Runs", "",
                               "The state is as of the release (or the watchdog); the owner may have changed a flag in GrowthBook since. A dark flag was never released: its story is labelled `dark-broken` once its retries are used up.", ""]
    return "\n".join(lines + flag_rows(data["flags"])) + "\n\n" + app_state_record.dump(data) + "\n"


def render_registry(prev_body, d, state_url):
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


def gh_text(args, token, check=False):
    return sh(["gh", *args], env={**os.environ, "GH_TOKEN": token}, check=check).stdout


def write_body_file(body):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(body)
    return f.name


def create_state_issue(repo, token, label, title, color, body):
    gh_text(["label", "create", label, "--repo", repo, "--color", color, "--description", "Maintained by the Orchestrator"], token)
    made = gh_text(["issue", "create", "--repo", repo, "--label", label, "--title", title, "--body-file", write_body_file(body)], token)
    m = re.search(r"https://\S+/issues/(\d+)", made)
    if m:
        gh_text(["issue", "pin", m.group(1), "--repo", repo], token)
    return m.group(0) if m else ""


def upsert_state_issue(repo, token, label, title, color, render):
    found = json.loads(gh_text(["issue", "list", "--repo", repo, "--label", label, "--state", "open", "--json", "number,body,url"], token, check=True) or "[]")
    body = render(found[0]["body"] if found else "")
    if not found:
        return create_state_issue(repo, token, label, title, color, body)
    gh_text(["issue", "edit", str(found[0]["number"]), "--repo", repo, "--body-file", write_body_file(body)], token)
    return found[0]["url"]


def update_state_issues(d, factory_repo, pat, factory_token):
    try:
        app_repo = f"{factory_repo.split('/')[0]}/{d['app']}"
        state_url = upsert_state_issue(app_repo, pat, app_state_record.STATE_LABEL, "Factory: app state", "5319e7", lambda prev: render_state(prev, d))
        upsert_state_issue(factory_repo, factory_token, app_state_record.REGISTRY_LABEL, "Factory: Managed Apps", "5319e7", lambda prev: render_registry(prev, d, state_url))
    except Exception as e:  # noqa: BLE001
        print(f"could not update the state issues: {type(e).__name__}", flush=True)
