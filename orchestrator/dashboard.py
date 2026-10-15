#!/usr/bin/env python3
"""A static dashboard of the Factory's Build Runs, and a daily digest.

Each Build Run uploads its Report as an artifact, and artifacts expire. This keeps the history: it collects
the Reports of runs it has not seen yet, merges them into `history.json`, and renders `index.html` beside it.
The scheduled workflow (.github/workflows/dashboard.yml) keeps both files on the `factory-data` branch, which
GitHub Pages can serve if it is enabled for that branch; the digest goes to the workflow's run summary.

No server, no database and no new always-on service. The pure functions (summarize, merge, metrics, render)
are unit-tested; `collect` and `main` talk to GitHub through `gh`.

Usage: dashboard.py <data-dir>        (env GH_TOKEN and GITHUB_REPOSITORY; GITHUB_STEP_SUMMARY optional)
"""
import calendar
import html
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OK = ("released", "nothing_to_release", "planned")
WORKFLOW = "build-run.yml"
MAX_RUNS_PER_PASS = 100
COST_TARGET_USD = 1.0  # the owner's goal for one Build Run; a target, not a cap (the cap is `limits.cost_cap_usd_default`)


def summarize_run(d):
    """One Report -> one history row (only what the dashboard shows, so history stays small)."""
    started, finished = d.get("started_at") or "", d.get("finished_at") or ""
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        minutes = round((calendar.timegm(time.strptime(finished, fmt)) - calendar.timegm(time.strptime(started, fmt))) / 60, 1)
    except ValueError:
        minutes = None
    ver = (d.get("verification") or {}).get("counts") or {}
    return {"run_url": d.get("run_url") or "", "app": d.get("app") or "?", "outcome": d.get("outcome") or "?",
            "kind": d.get("build_kind") or "", "started_at": started, "minutes": minutes,
            "rounds": d.get("review_passes") or 0, "cost_usd": round(d.get("spent_usd") or 0, 4), "cap_usd": d.get("cap_usd"),
            "released": (d.get("release") or {}).get("released") or [], "checks": ver,
            "audit": [a.get("rule", "") for a in d.get("audit") or []]}


def merge_history(history, rows):
    """History plus new rows, one per run_url (a newer row replaces an older one), oldest first."""
    by_url = {r["run_url"]: r for r in history if r.get("run_url")}
    by_url.update({r["run_url"]: r for r in rows if r.get("run_url")})
    return sorted(by_url.values(), key=lambda r: r.get("started_at") or "")


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _p90(xs):
    """The value 90% of the runs are at or below (nearest rank), or None for no runs."""
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, -(-9 * len(xs) // 10) - 1)], 2) if xs else None


def metrics(history, lessons=None):
    """Fleet numbers, overall and per app. `lessons` is {"open": n, "fix_ineffective": n} or None."""
    def block(rows):
        ok = [r for r in rows if r["outcome"] in OK]
        return {"runs": len(rows), "ok": len(ok),
                "ok_rate": round(len(ok) / len(rows), 2) if rows else None,
                "first_pass_rate": round(sum(1 for r in ok if r["rounds"] <= 1) / len(ok), 2) if ok else None,
                "avg_rounds": _avg([r["rounds"] for r in rows if r["rounds"]]),
                "avg_cost_usd": _avg([r["cost_usd"] for r in rows]),
                "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 2),
                "p90_cost_usd": _p90([r["cost_usd"] for r in rows]),
                "over_target": sum(1 for r in rows if r["cost_usd"] > COST_TARGET_USD),
                "stuck": sum(1 for r in rows if r["outcome"] in ("stuck", "round_limit")),
                "watchdog_disabled": sum(1 for r in rows if r["outcome"] == "watchdog_disabled"),
                "needs_human": sum(1 for r in rows if r["outcome"] not in OK),
                "audit_violations": sum(len(r["audit"]) for r in rows)}

    apps = {}
    for r in history:
        apps.setdefault(r["app"], []).append(r)
    return {"all": block(history), "apps": {a: block(rs) for a, rs in sorted(apps.items())}, "lessons": lessons or {}}


def pct(x):
    return "-" if x is None else f"{round(x * 100)}%"


def num(x, prefix=""):
    return "-" if x is None else f"{prefix}{x}"


def render_digest(history, m, since):
    """Markdown for the daily summary: what happened since `since` (an ISO timestamp) and what needs a person."""
    recent = [r for r in history if (r.get("started_at") or "") >= since]
    allm = m["all"]
    lines = ["## Factory digest", "",
             f"**Last day**: {len(recent)} Build Run(s), {sum(1 for r in recent if r['outcome'] in OK)} ended OK, "
             f"${sum(r['cost_usd'] for r in recent):.2f} spent.",
             f"**All time**: {allm['runs']} runs, {pct(allm['ok_rate'])} OK, {pct(allm['first_pass_rate'])} first pass, "
             f"avg {num(allm['avg_rounds'])} rounds, avg {num(allm['avg_cost_usd'], '$')}, total {num(allm['total_cost_usd'], '$')}.",
             f"**Cost target** (${COST_TARGET_USD:.2f} a run): {allm['over_target']} of {allm['runs']} run(s) over it, 90th percentile {num(allm['p90_cost_usd'], '$')}."]
    attention = [r for r in recent if r["outcome"] not in OK]
    if attention:
        lines += ["", "**Needs a person**:"] + [f"- `{r['app']}`: {r['outcome']} ([run]({r['run_url']}))" for r in attention]
    broken = [r for r in recent if r["audit"]]
    if broken:
        lines += ["", "**Invariants broken in a real run**:"] + [f"- `{r['app']}`: {', '.join(r['audit'])} ([run]({r['run_url']}))" for r in broken]
    les = m.get("lessons") or {}
    if les:
        lines += ["", f"**Lessons**: {les.get('open', 0)} open, {les.get('fix_ineffective', 0)} marked fix-ineffective."]
    if not attention and not broken:
        lines += ["", "Nothing needs a person."]
    return "\n".join(lines) + "\n"


STYLE = """:root{--bg:#fff;--fg:#1b1f24;--muted:#5b6570;--line:#d8dde3;--ok:#1a7f37;--bad:#b42318;--card:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#0f1317;--fg:#e6e9ed;--muted:#97a1ac;--line:#2a323a;--ok:#4ac26b;--bad:#ff7b72;--card:#171c22}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}main{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:2rem}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.card b{display:block;font-size:1.3rem}.card span{color:var(--muted);font-size:.85rem}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:560px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);font-size:.9rem}
th{color:var(--muted);font-weight:600}.ok{color:var(--ok)}.bad{color:var(--bad)}a{color:inherit}"""


def render_html(history, m, generated):
    e = html.escape
    allm = m["all"]
    cards = [("Runs", allm["runs"]), ("OK", pct(allm["ok_rate"])), ("First pass", pct(allm["first_pass_rate"])),
             ("Avg rounds", num(allm["avg_rounds"])), ("Avg cost", num(allm["avg_cost_usd"], "$")), ("90th pct cost", num(allm["p90_cost_usd"], "$")),
             (f"Over ${COST_TARGET_USD:.0f}", allm["over_target"]), ("Total cost", num(allm["total_cost_usd"], "$")),
             ("Stuck", allm["stuck"]), ("Watchdog off", allm["watchdog_disabled"]), ("Audit breaks", allm["audit_violations"])]
    les = m.get("lessons") or {}
    if les:
        cards += [("Lessons open", les.get("open", 0)), ("Fix ineffective", les.get("fix_ineffective", 0))]
    out = ["<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
           "<title>Factory dashboard</title>", f"<style>{STYLE}</style><main>", "<h1>Factory dashboard</h1>",
           f"<p class=muted>Generated {e(generated)} from {allm['runs']} Build Run Report(s).</p>", "<div class=cards>"]
    out += [f"<div class=card><b>{e(str(v))}</b><span>{e(k)}</span></div>" for k, v in cards]
    out += ["</div>", "<h2>Apps</h2><div class=scroll><table><tr><th>App<th>Runs<th>OK<th>First pass<th>Avg rounds<th>Avg cost<th>Total<th>Needs a person</tr>"]
    for app, a in m["apps"].items():
        out.append(f"<tr><td>{e(app)}<td>{a['runs']}<td>{pct(a['ok_rate'])}<td>{pct(a['first_pass_rate'])}<td>{num(a['avg_rounds'])}"
                   f"<td>{num(a['avg_cost_usd'], '$')}<td>{num(a['total_cost_usd'], '$')}<td>{a['needs_human']}</tr>")
    out += ["</table></div>", "<h2>Recent runs</h2><div class=scroll><table><tr><th>Started<th>App<th>Kind<th>Outcome<th>Rounds<th>Cost<th>Min<th>Released<th>Audit</tr>"]
    for r in reversed(history[-100:]):
        cls = "ok" if r["outcome"] in OK else "bad"
        link = f"<a href='{e(r['run_url'], quote=True)}'>{e(r['outcome'])}</a>" if r["run_url"].startswith("https://") else e(r["outcome"])
        out.append(f"<tr><td>{e(r['started_at'][:16].replace('T', ' '))}<td>{e(r['app'])}<td>{e(r['kind'])}<td class={cls}>{link}"
                   f"<td>{r['rounds']}<td>${r['cost_usd']:.2f}<td>{num(r['minutes'])}<td>{len(r['released'])}<td>{e(', '.join(r['audit']) or '-')}</tr>")
    out.append("</table></div></main></html>")
    return "".join(out) + "\n"


# --- GitHub (not unit-tested) -------------------------------------------------


def gh_json(args):
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    return json.loads(p.stdout or "[]") if p.returncode == 0 else []


def collect(repo, known_urls):
    """Reports of recent Build Runs not yet in history, read from each run's `build-run` artifact."""
    rows = []
    runs = gh_json(["run", "list", "--repo", repo, "--workflow", WORKFLOW, "--limit", str(MAX_RUNS_PER_PASS),
                    "--status", "completed", "--json", "databaseId,url"])
    for run in runs:
        if run["url"] in known_urls:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            p = subprocess.run(["gh", "run", "download", str(run["databaseId"]), "--repo", repo, "-n", "build-run", "-D", tmp],
                               capture_output=True, text=True)
            report = next(Path(tmp).rglob("build-run-report.json"), None) if p.returncode == 0 else None
            if report:
                rows.append(summarize_run(json.loads(report.read_text())))
    return rows


def lesson_counts(repo):
    issues = gh_json(["issue", "list", "--repo", repo, "--label", "factory-learning", "--state", "all", "--limit", "200",
                      "--json", "state,labels"])
    return {"open": sum(1 for i in issues if i["state"] == "OPEN"),
            "fix_ineffective": sum(1 for i in issues if i["state"] == "OPEN" and any(l["name"] == "fix-ineffective" for l in i["labels"]))}


def main(argv):
    data = Path(argv[1])
    data.mkdir(parents=True, exist_ok=True)
    repo = os.environ["GITHUB_REPOSITORY"]
    hist_path = data / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else []
    history = merge_history(history, collect(repo, {r["run_url"] for r in history}))
    m = metrics(history, lesson_counts(repo))
    now = time.gmtime()
    hist_path.write_text(json.dumps(history, indent=1) + "\n")
    (data / "index.html").write_text(render_html(history, m, time.strftime("%Y-%m-%d %H:%M UTC", now)))
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
    digest = render_digest(history, m, since)
    print(digest)
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a") as f:
        f.write(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
