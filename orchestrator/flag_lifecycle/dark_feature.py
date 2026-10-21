# A dark feature: flagged code that never got through its checks. It stays dark, is labelled on its story, and is removed only when a person approves.
import os

from shared import github, outcomes, shell

from flag_lifecycle import story_link

DARK_BROKEN = "dark-broken"


def is_dark_broken(d):
    # Whether the run left a dark feature behind: it pushed code behind a flag and ended without releasing it (or with the watchdog
    # having switched the release off, or the tester having found a regression and the deploy been rolled back). The code stays in `main`,
    # behind a flag that is off, and is fixed forward by a fix child. The flag is the identity of a dark feature, and its
    # story issue (`flag:<slug>`) carries this label; `flags.json` does not, because every edit to it deploys.
    return bool(d.get("flags") and d.get("commits")) and d.get("outcome") not in outcomes.OK + outcomes.ANSWERED + (outcomes.PROVIDER_BLOCKED,)


def label_dark_feature(d, repo, token):
    # Mark the story issue `dark-broken` when the run left a dark feature, and take the mark off when the story is released at last.
    # Best effort: a label that cannot be set never changes the run's ending.
    number = d.get("issue_number")
    try:
        env = {**os.environ, "GH_TOKEN": token}
        if is_dark_broken(d):
            github.ensure_label(repo, DARK_BROKEN, token, "b60205", "A dark feature that failed its checks; fixed forward by a fix child")
            labels = [DARK_BROKEN] + [l for l in (story_link.flag_label(slug) for slug in d["flags"]) if l]  # the story names its flag, released or not
            for name in labels[1:]:
                github.ensure_label(repo, name, token, "0e8a16", "The feature flag this story's change is behind")
            shell.sh(["gh", "issue", "edit", str(number), "--repo", repo, "--add-label", ",".join(labels)], env=env, check=False)
        elif d.get("outcome") == "released":
            shell.sh(["gh", "issue", "edit", str(number), "--repo", repo, "--remove-label", f"{DARK_BROKEN},bug"], env=env, check=False)
    except Exception as e:  # noqa: BLE001
        print(f"could not label the dark feature: {type(e).__name__}", flush=True)


APPROVE = "approve-retire"


def dark_removal_target(labels):
    # (app, slug, None) when a person's approval can retire this story's dark feature, else (None, None, why not).
    labels = set(labels)
    if "update-app-intake" not in labels:
        return None, None, "this is not an Update App Intake story"
    if DARK_BROKEN not in labels:
        return None, None, f"the story has no broken dark feature (it is not labelled `{DARK_BROKEN}`)"
    if "needs-human" not in labels:
        return None, None, "the automatic retries are not used up yet (the story is not labelled `needs-human`); they fix it forward first"
    slugs = sorted(l[5:] for l in labels if l.startswith("flag:"))
    apps = sorted(l[4:] for l in labels if l.startswith("app:"))
    if len(slugs) != 1 or len(apps) != 1:
        return None, None, "the story must name exactly one flag (`flag:<slug>`) and one app (`app:<name>`)"
    return apps[0], slugs[0], None


def dark_removal_task(slug, story):
    # The request an approved retirement files: remove the feature, since it never released. Users see no difference.
    return (f"Remove the dark feature behind the flag `{slug}`. It was built in #{story}, never passed its checks and was never released, "
            "so no user has ever seen it and its flag is off. A person has approved removing it.\n\n"
            f"Delete the check of `{slug}`, the code it guarded (routes, UI, helpers, migrations that only it used) and the tests that "
            f"exercise it; remove its entry from `flags.json`. Leave no code that mentions the slug (a comment may). Touch no other flag and "
            "change nothing else: the app must behave exactly as it does today.")
