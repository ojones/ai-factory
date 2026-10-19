# A flag and the story it belongs to point at each other (INV-38): the `flag:<slug>` label, the flag in the title, and the GrowthBook description and tags.
import re

FLAG_TAG_RE = re.compile(r"\s*\[flags?: [^\]]*\]")


def flag_label(slug):
    # The label that marks a story with its flag (GitHub labels hold 50 characters), or None for a slug too long to fit.
    name = f"flag:{slug}"
    return name if len(name) <= 50 else None


def title_with_flags(title, slugs):
    # The issue title carrying its flag(s), `... [flag: slug]`, replacing any earlier such tag; unchanged for no slugs.
    if not slugs:
        return title
    base = FLAG_TAG_RE.sub("", title or "").rstrip()
    return f"{base} [{'flag' if len(slugs) == 1 else 'flags'}: {', '.join(slugs)}]"


def flag_description(issue_url, title):
    # What a GrowthBook feature says about the story it came from: the issue link first, so the two can be followed both ways.
    return f"{issue_url} {FLAG_TAG_RE.sub('', title or '').strip()}"[:300].strip()


def flag_tags(issue, app):
    return [f"intake-{issue}", f"app-{app}"]


def link(run_gh, ensure_label, repo, token, issue, title, app, run_id, run_url, slugs):
    # The story names its flag: a `flag:<slug>` label, the flag in the title, and a comment with the full key (the flag, in turn, links
    # back through its GrowthBook description and tag). `run_gh(args, token=, check=)` runs gh. Returns the issue's title afterwards.
    for slug in slugs:
        label = flag_label(slug)
        if label:
            ensure_label(repo, label, token, "5319e7", "The feature flag of this story")
            run_gh(["issue", "edit", issue, "--repo", repo, "--add-label", label], token=token, check=False)
    new_title = title_with_flags(title, slugs)
    if new_title and new_title != title:
        run_gh(["issue", "edit", issue, "--repo", repo, "--title", new_title], token=token, check=False)
        title = new_title
    keys = ", ".join(f"`{app}.feature.{s}`" for s in slugs)
    run_gh(["issue", "comment", issue, "--repo", repo, "--body",
            f"Feature flag {keys}: released by [Build Run {run_id}]({run_url}). The flag in GrowthBook links back here."], token=token, check=False)
    return title
