import json
import os
import re
import sys

from shared import config, github
from try_fix import factory_fix_request, render_bug

from factory_change import file_change

SOURCE_LABEL = factory_fix_request.FACTORY_LABEL
MOVED_LABEL = "moved-to-factory-change"
CAUSE = "orchestrator_gap"
NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.+)$", re.M)


def sightings(issue):
    return 1 + sum(1 for c in issue.get("comments") or [] if (c.get("body") or "").startswith("**Failed again"))


def finding_of(issue):
    sections = file_change.sections(issue["body"])
    return {"fingerprint": render_bug.read_key(issue["body"]), "summary": re.sub(r"\s*\[[0-9a-f]+\]\s*", " ", issue["title"]).strip(),
            "failure": sections.get("what happened", ""), "requirements": [r.strip() for r in NUMBERED.findall(sections.get("requirements", ""))],
            "reproduction": file_change.NO_REPRODUCTION, "evidence": sections.get("how it was found", ""),
            "failed_child": factory_fix_request.read_failed_child(issue["body"])}


def wanted(issue, promote_after):
    names = {x["name"] for x in issue.get("labels") or []}
    cause = file_change.sections(issue["body"]).get("cause", "").strip()
    return MOVED_LABEL not in names and cause == CAUSE and bool(render_bug.read_key(issue["body"])) and sightings(issue) >= promote_after


def move(repo, pat, issue, max_criteria):
    got = file_change.file_change(repo, pat, finding_of(issue), max_criteria)
    if got["action"] in ("filed", "seen_again"):
        github.ensure_label(repo, MOVED_LABEL, pat, "ededed", "Handled by the Factory Change process")
        github.run(["issue", "edit", str(issue["number"]), "--repo", repo, "--add-label", MOVED_LABEL], pat)
        github.run(["issue", "comment", str(issue["number"]), "--repo", repo, "--body", f"Handed to the Factory Change process (#{got.get('number')})."], pat)
    return got


def sweep(repo, pat, limits):
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--label", SOURCE_LABEL, "--state", "open", "--json", "number,title,body,labels,comments"], pat).stdout or "[]")
    after = int(limits.get("promote_after_runs", 2))
    return {i["number"]: move(repo, pat, i, int(limits.get("planner_max_criteria", 6)))["action"] for i in found if wanted(i, after)}


def main():
    print(sweep(os.environ["GITHUB_REPOSITORY"], os.environ["FACTORY_PAT"], config.load()["limits"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
