from shared.run_stops import NeedsHuman

from flag_lifecycle import flag_manifest


def feature_is_off_in_production(existing):
    prod = (((existing.get("feature") or existing) if isinstance(existing, dict) else {}).get("environments") or {}).get("production") or {}
    return prod.get("enabled") is False


def check_flags(gb, app, flags, own):
    for slug in flags:
        if not flag_manifest.SLUG_RE.fullmatch(slug):
            raise NeedsHuman("other", f"flag slug {slug!r} is not a valid slug; nothing released")
    to_switch, kept, missing = [], [], []
    for slug in flags:
        key = f"{app}.feature.{slug}"
        status, existing = gb("GET", f"/features/{key}")
        if status != 200:
            missing.append(slug)
        elif slug in own and feature_is_off_in_production(existing):
            to_switch.append(key)
        else:
            kept.append(key)
    return to_switch, kept, missing


def switch_on(gb, keys):
    for key in keys:
        gb("POST", f"/features/{key}", {"environments": {"production": {"enabled": True, "rules": []}}})
