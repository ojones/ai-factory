DEFAULTS = {"enabled": True, "min_occurrences": 3, "max_per_app_per_day": 2}


def decide(groups, open_by_fp, open_for_app, created_today, cfg):
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
    return open_for_app + reported < 1 and created_today + reported < int(cfg["max_per_app_per_day"])
