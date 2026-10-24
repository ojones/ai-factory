import collections
import json
import time
from pathlib import Path


def previous_report(work, rnd):
    path = Path(work) / f"test-report-{rnd - 1}.json"
    return path if rnd > 1 and path.exists() else "none (this is the first test pass)"


CHECK_STATES = ("passed", "failed", "blocked", "not_run")


def check_key(c):
    return f"{c['flag']}: {c['check']}" if c.get("flag") else c["check"]


def scoreboard_entry(rnd, sha, record, blocking):
    return {"round": rnd, "sha": sha, "counts": record["counts"],
            "checks": {check_key(c): c["status"] for c in record["checks"]},
            "blocking": sorted({" ".join(str(b.get("summary", "")).lower().split()) for b in blocking}),
            "categories": dict(collections.Counter(b.get("category") or f"{b.get('source', 'other')}_check" for b in blocking))}


class State:
    def __init__(self, path, app, issue, run_url):
        self.path = Path(path)
        self.d = {"app": app, "issue_number": issue, "run_url": run_url, "outcome": "running", "message": "",
                  "cap_usd": None, "spent_usd": 0.0, "base_sha": None, "head_sha": None, "review_passes": 0,
                  "commits": [], "stages": [], "release": None, "blocking": [], "verification": None, "scoreboard": [],
                  "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=2))
        tmp.replace(self.path)

    def stage(self, name, agent, rnd, cost, verdict, usage=None):
        self.d["stages"].append({"stage": name, "agent": agent, "round": rnd,
                                 "cost_usd": round(cost, 6), "verdict": verdict, "usage": usage})
        self.save()
        return self.d["stages"][-1]


class TrackProgress:
    def record_round(self, rnd, head, blocking):
        record = self.state.d.get("verification")
        if not record or record.get("round") != rnd:
            record = {"round": rnd, "sha": head, "counts": {s: 0 for s in CHECK_STATES}, "checks": [], "limitations": []}
        self.state.d["scoreboard"].append(scoreboard_entry(rnd, head, record, blocking))
        self.state.save()
        (self.art / "progress.json").write_text(json.dumps(self.state.d["scoreboard"], indent=2))
