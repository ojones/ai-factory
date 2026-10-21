import json

from shared import child_tickets
from shared.run_stops import NeedsHuman

from flag_lifecycle import story_link

SLOT = child_tickets.FLAG_SLOT


def for_story(story_number):
    return f"issue-{int(story_number)}"


def name_in(text, slug):
    return (text or "").replace(SLOT, slug)


def ensure_feature(gb, app, slug, issue_url, issue_title, issue_number):
    key = f"{app}.feature.{slug}"
    status, _ = gb("GET", f"/features/{key}")
    if status == 200:
        return False
    status, projects = gb("GET", "/projects?limit=100")
    if status != 200 or not (projects or {}).get("projects"):
        raise NeedsHuman("other", f"could not create the flag {key}: GrowthBook answered HTTP {status} for its projects")
    feature = {"id": key, "owner": "ai-factory", "valueType": "boolean", "defaultValue": "true", "project": projects["projects"][0]["id"],
               "environments": {"production": {"enabled": False, "rules": []}}}
    status, r = gb("POST", "/features", {**feature, "description": story_link.flag_description(issue_url, issue_title),
                                          "tags": story_link.flag_tags(issue_number, app)})
    if status == 400:
        status, r = gb("POST", "/features", feature)
    if status != 200:
        raise NeedsHuman("other", f"could not create the flag {key}: HTTP {status} {r}")
    return True


def add_to_manifest(flags_json, slug, issue_ref, summary):
    try:
        flags = json.loads(flags_json) if (flags_json or "").strip() else []
    except ValueError:
        raise NeedsHuman("other", "flags.json is not valid JSON, so the story's flag cannot be recorded in it")
    if any(isinstance(f, dict) and f.get("slug") == slug for f in flags):
        return flags_json
    flags.append({"slug": slug, "description": f"{issue_ref}: {' '.join(str(summary).split())[:120]}"})
    return json.dumps(flags, indent=2) + "\n"
