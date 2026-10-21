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
HANDOFF = re.compile(r"Handed to the Factory Change process \(#(\d+)\)\. Sightings: (\d+)")
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


def comment_bodies(issue):
    return [c.get("body") or "" for c in issue.get("comments") or []]


def handoff_of(issue):
    found = (HANDOFF.match(body) for body in comment_bodies(issue))
    return next((m for m in found if m), None)


def relays_due(issue, handoff):
    returned = sightings(issue) - int(handoff.group(2))
    relayed = sum(1 for body in comment_bodies(issue) if body.startswith("**Relayed"))
    return returned - relayed


def relay(repo, pat, issue, max_criteria):
    got = file_change.file_change(repo, pat, finding_of(issue), max_criteria)
    if got["action"] == "seen_again":
        github.run(["issue", "comment", str(issue["number"]), "--repo", repo, "--body", f"**Relayed** to the Factory Change process (#{got['number']})."], pat)
    return got


def move(repo, pat, issue, max_criteria):
    got = file_change.file_change(repo, pat, finding_of(issue), max_criteria)
    if got["action"] in ("filed", "seen_again"):
        github.ensure_label(repo, MOVED_LABEL, pat, "ededed", "Handled by the Factory Change process")
        github.run(["issue", "edit", str(issue["number"]), "--repo", repo, "--add-label", MOVED_LABEL], pat)
        github.run(["issue", "comment", str(issue["number"]), "--repo", repo, "--body", f"Handed to the Factory Change process (#{got.get('number')}). Sightings: {sightings(issue)}."], pat)
    return got


def returning(issue):
    handoff = handoff_of(issue)
    return bool(handoff) and relays_due(issue, handoff) > 0


def sweep(repo, pat, limits):
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--label", SOURCE_LABEL, "--state", "open", "--json", "number,title,body,labels,comments"], pat).stdout or "[]")
    after = int(limits.get("promote_after_runs", 2))
    criteria = int(limits.get("planner_max_criteria", 6))
    moved = {i["number"]: move(repo, pat, i, criteria)["action"] for i in found if wanted(i, after)}
    returned = [i for i in found if returning(i)]
    return {**moved, **{i["number"]: relay(repo, pat, i, criteria)["action"] for i in returned}}


def main():
    print(sweep(os.environ["GITHUB_REPOSITORY"], os.environ["FACTORY_PAT"], config.load()["limits"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
