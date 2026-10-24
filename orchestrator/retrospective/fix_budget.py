import json
from datetime import datetime, timezone

from request import intake_labels

from retrospective import tracker


def bugs_filed_today(repo, token, app, now=None):
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    out = tracker.gh(["issue", "list", "--repo", repo, "--label", "bug", "--label", intake_labels.app_label(app), "--state", "all",
                      "--search", f"created:>={day}", "--json", "number", "--limit", "50"], token, check=True).stdout
    return len(json.loads(out or "[]"))
