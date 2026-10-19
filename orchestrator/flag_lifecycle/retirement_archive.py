# A retired flag leaves nothing behind: the flags a run removed from `flags.json` are archived in GrowthBook (it cannot delete one).
from flag_lifecycle import flag_manifest


def archive_removed(gb, app, base_flags_json, head_flags_json):
    # Archives each flag in the base manifest that is not in the head, best effort. Returns [(slug, HTTP status)].
    done = []
    for slug in flag_manifest.removed_flag_slugs(base_flags_json, head_flags_json):
        status, _ = gb("POST", f"/features/{app}.feature.{slug}", {"archived": True})
        done.append((slug, status))
    return done
