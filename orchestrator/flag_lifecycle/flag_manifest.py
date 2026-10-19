# What a Managed App's `flags.json` and a flag's name say: which slugs are in the manifest, which a run added or removed, and the GrowthBook key.
import json
import re

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def manifest_slugs(flags_json):
    try:
        return {f["slug"] for f in json.loads(flags_json or "[]") if isinstance(f, dict) and isinstance(f.get("slug"), str)}
    except ValueError:
        return set()


def removed_flag_slugs(base_flags_json, head_flags_json):
    # Slugs that were in the manifest at the base and are not at the head: the flags a run retired.
    return sorted(manifest_slugs(base_flags_json) - manifest_slugs(head_flags_json))


def new_flag_slugs(base_json, head_json):
    def slugs(text):
        try:
            return [e["slug"] for e in json.loads(text) if isinstance(e, dict) and "slug" in e]
        except (ValueError, TypeError):
            return []
    base = set(slugs(base_json))
    return [s for s in slugs(head_json) if s not in base]


def feature_key(app, slug):
    # The GrowthBook key, or None if the app or slug is not a valid name (so nothing odd is ever put in a URL).
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", app or "") or not SLUG_RE.fullmatch(slug or ""):
        return None
    return f"{app}.feature.{slug}"
