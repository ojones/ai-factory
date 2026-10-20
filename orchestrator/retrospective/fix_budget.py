# STEP 6.2: how many bug tickets the Factory already filed for an app today (UTC), so `fix_events_per_app_per_day` can stop a noisy app's warnings from
# turning into a stream of fixes. Every bug Intake counts (label `bug` and `app:<app>` in ai-factory); failures are not limited by it, only warnings.
import json
from datetime import datetime, timezone

from request import intake_labels

from retrospective import tracker


def warnings_fixed_today(repo, token, app, now=None):
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    out = tracker.gh(["issue", "list", "--repo", repo, "--label", "bug", "--label", intake_labels.app_label(app), "--state", "all",
                      "--search", f"created:>={day}", "--json", "number", "--limit", "50"], token).stdout
    return len(json.loads(out or "[]"))
