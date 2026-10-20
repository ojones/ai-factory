# STEP 8.3: flood control for production feedback (INV-31). A production error cannot flood the trackers or the budget: nothing below `min_occurrences` in a scan, one
# open bug per error (a repeat adds a comment with the count, never a second ticket), at most one open bug per app at a time, and at most `max_per_app_per_day` new
# ones per app per day. Pure decisions, tested alone; the counts come from the bug Intakes in ai-factory (label `bug` and `app:<app>`).
DEFAULTS = {"enabled": True, "min_occurrences": 3, "max_per_app_per_day": 2}


def decide(groups, open_by_fp, open_for_app, created_today, cfg):
    # (new fingerprints to report, fingerprints to comment on). `open_by_fp` maps a fingerprint to the open bug already filed for it, `open_for_app` is how many bugs the
    # app has open, `created_today` how many were filed today.
    minimum, room = int(cfg["min_occurrences"]), int(cfg["max_per_app_per_day"]) - created_today
    new, seen_again = [], []
    for fp, g in sorted(groups.items(), key=lambda kv: -kv[1]["count"]):
        if g["count"] < minimum:
            continue
        if fp in open_by_fp:
            seen_again.append(fp)
        elif open_for_app + len(new) < 1 and room - len(new) > 0:
            new.append(fp)
    return new, seen_again


def defects_room(open_for_app, created_today, reported, cfg):
    # Whether another owner-reported defect may be reported now, given `reported` already this scan.
    return open_for_app + reported < 1 and created_today + reported < int(cfg["max_per_app_per_day"])
