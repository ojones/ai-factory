# A person approved removing a dark feature: file the removal as an Update App Intake, start it, and close the story. Run by approve-retire.yml.
import json
import os
import sys

from request import file_intake
from shared import shell

from flag_lifecycle import dark_feature


def approve(repo, pat, number):
    # The story #number got the label `approve-retire`: file the removal as an Update App Intake and start it. Returns 0 either way (a refusal
    # is a comment on the story, not a failed workflow).
    env = {**os.environ, "GH_TOKEN": pat}
    story = json.loads(shell.sh(["gh", "issue", "view", str(number), "--repo", repo, "--json", "labels,title"], env=env).stdout)
    labels = [l["name"] for l in story["labels"]]
    app, slug, why = dark_feature.dark_removal_target(labels)
    shell.sh(["gh", "issue", "edit", str(number), "--repo", repo, "--remove-label", dark_feature.APPROVE], env=env, check=False)
    if why:
        shell.sh(["gh", "issue", "comment", str(number), "--repo", repo, "--body", f"**Retirement not started:** {why}."], env=env, check=False)
        return 0
    made = file_intake.file_update_app_intake(repo, pat, pat, app, f"{app}: Remove dark feature {slug}", dark_feature.dark_removal_task(slug, number), check=True)
    if made is None:
        return 0
    shell.sh(["gh", "issue", "comment", str(number), "--repo", repo, "--body",
          f"**Retirement approved.** The dark feature `{slug}` is being removed by #{made}. This story is closed; the removal "
          "leaves the app exactly as it is today."], env=env, check=False)
    shell.sh(["gh", "issue", "close", str(number), "--repo", repo, "--reason", "not planned"], env=env, check=False)
    return 0


def main(argv):
    if len(argv) > 2 and argv[1] == "approve":
        return approve(os.environ["FACTORY_REPO"], os.environ["FACTORY_PAT"], int(argv[2]))
    print("usage: approve_retire.py approve <story issue number>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
