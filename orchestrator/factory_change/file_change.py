import json
import re

from shared import github
from try_fix import factory_fix_request, validate_bug

from factory_change import pause, prove_reproduction, stop

LABEL = "factory-change"
INEFFECTIVE = "fix-ineffective"
SECTION = re.compile(r"^#{2,4} (.+?)\n(.*?)(?=^#{2,4} |\Z)", re.M | re.S)
NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.+)$", re.M)
NO_REPRODUCTION = "none"


def sections(body):
    return {name.strip().lower(): text.strip() for name, text in SECTION.findall(body or "")}


def requirements_of(body):
    return [r.strip() for r in NUMBERED.findall(sections(body).get("requirements", ""))]


def reproduction_of(body):
    return sections(body).get("reproduction", "").strip().strip("`").strip()


def ticket_problems(body, max_criteria):
    found = sections(body)
    problems = [] if found.get("observable failure") else ["the ticket names no observable failure"]
    problems += validate_bug.requirement_problems(requirements_of(body), max_criteria)
    reproduction = reproduction_of(body)
    if reproduction.lower() != NO_REPRODUCTION and not prove_reproduction.valid_name(reproduction):
        problems.append("the reproduction is neither a test name (module.Class.test) nor `none`")
    return problems


def render(finding):
    numbered = "\n".join(f"{n}. {r}" for n, r in enumerate(finding["requirements"], 1))
    resume = factory_fix_request.failed_child_marker(finding["failed_child"]) + "\n" if finding.get("failed_child") else ""
    return (f"{finding['summary']}\n\n## Observable failure\n{finding['failure']}\n\n## Requirements\n{numbered}\n\n"
            f"## Reproduction\n{finding.get('reproduction') or NO_REPRODUCTION}\n\n## Evidence\n{finding['evidence']}\n\n{resume}")


def find_existing(repo, token, fingerprint):
    found = github.run(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "all", "--search", f"{fingerprint} in:title",
                        "--json", "number,title,state,url"], token).stdout
    return next((i for i in json.loads(found or "[]") if fingerprint in i["title"]), None)


def seen_again(repo, token, existing, finding):
    note = f"**Seen again:** {finding['summary']}\n{finding['evidence']}"
    if existing["state"].lower() == "closed":
        github.run(["issue", "reopen", str(existing["number"]), "--repo", repo], token)
        github.ensure_label(repo, INEFFECTIVE, token, "e99695", "A merged fix did not hold")
        github.run(["issue", "edit", str(existing["number"]), "--repo", repo, "--add-label", INEFFECTIVE], token)
    stop.comment(repo, token, existing["number"], note)
    return {"action": "seen_again", "number": existing["number"]}


def create(repo, token, finding):
    github.ensure_label(repo, LABEL, token, "5319e7", "A change to the Factory's own code, planned and delivered by the Factory")
    out = github.run(["issue", "create", "--repo", repo, "--label", LABEL, "--title", f"Factory Change [{finding['fingerprint']}]: {finding['summary'][:80]}",
                      "--body", render(finding)], token)
    made = re.search(r"/issues/(\d+)", out.stdout or "")
    return {"action": "filed", "number": int(made.group(1)) if made else None}


def file_change(repo, token, finding, max_criteria):
    if pause.is_paused(repo, token):
        return {"action": "paused"}
    existing = find_existing(repo, token, finding["fingerprint"])
    if existing:
        return seen_again(repo, token, existing, finding)
    problems = ticket_problems(render(finding), max_criteria)
    return {"action": "refused", "problems": problems} if problems else create(repo, token, finding)
