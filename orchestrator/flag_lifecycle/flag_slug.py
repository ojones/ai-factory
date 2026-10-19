# The flag of a story is named after its issue and created before any code is written (STEP 4.1, 5.1): `issue-<n>`, `<n>` the story's own number.
# A plan only says whether a change set is flagged; its task text carries SLOT where the slug goes, and the Build Run fills it in.
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
    # Creates the GrowthBook feature with production OFF (and the story's link and tag) unless it already exists; an existing feature is never
    # touched. Returns True when it was created. `gb(method, path, body)` returns (status, document).
    key = f"{app}.feature.{slug}"
    status, _ = gb("GET", f"/features/{key}")
    if status == 200:
        return False
    status, projects = gb("GET", "/projects?limit=100")
    if status != 200 or not (projects or {}).get("projects"):
        raise NeedsHuman("other", f"could not create the flag {key}: GrowthBook answered HTTP {status} for its projects")
    feature = {"id": key, "owner": "ai-factory", "valueType": "boolean", "defaultValue": "true", "project": projects["projects"][0]["id"],
               "environments": {"production": {"enabled": False, "rules": []}}}
    # The extras are the pointer back to the story; if GrowthBook refuses them the flag is still created without them.
    status, r = gb("POST", "/features", {**feature, "description": story_link.flag_description(issue_url, issue_title),
                                          "tags": story_link.flag_tags(issue_number, app)})
    if status == 400:
        status, r = gb("POST", "/features", feature)
    if status != 200:
        raise NeedsHuman("other", f"could not create the flag {key}: HTTP {status} {r}")
    return True


def add_to_manifest(flags_json, slug, issue_ref, summary):
    # `flags.json` text with the story's flag recorded, its description starting with the issue reference. Unchanged text when it is already there.
    try:
        flags = json.loads(flags_json) if (flags_json or "").strip() else []
    except ValueError:
        raise NeedsHuman("other", "flags.json is not valid JSON, so the story's flag cannot be recorded in it")
    if any(isinstance(f, dict) and f.get("slug") == slug for f in flags):
        return flags_json
    flags.append({"slug": slug, "description": f"{issue_ref}: {' '.join(str(summary).split())[:120]}"})
    return json.dumps(flags, indent=2) + "\n"
