from flag_lifecycle import flag_manifest


def archive_removed(gb, app, base_flags_json, head_flags_json):
    done = []
    for slug in flag_manifest.removed_flag_slugs(base_flags_json, head_flags_json):
        status, _ = gb("POST", f"/features/{app}.feature.{slug}", {"archived": True})
        done.append((slug, status))
    return done
