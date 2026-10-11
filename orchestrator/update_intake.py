#!/usr/bin/env python3
"""Update Intake: a change request for a Managed App that already exists.

An update Intake is a GitHub issue made from the "Update Intake" form (label `update-intake`). Adding the label
`proceed-with-change` starts it at once: `.github/workflows/update-intake.yml` runs `start`, which checks the issue
and dispatches a Build Run. There is no App Staging; the app, its repo and its flags already exist.

The Build Run then plans (agents/prompts/planner.md), and if the plan is one change set it codes, tests, reviews and
releases that change. If the plan has several change sets, the Build Run files one child issue per change set
(labels `update-intake`, `app:<slug>`, `plan:<parent>`) and ends. The first child with nothing to wait for gets
`proceed-with-change` straight away; the others get `waiting-on-plan`. When a child's Build Run succeeds, `advance`
gives `proceed-with-change` to the next sibling whose dependencies are now all closed (one at a time). So the children run one after
another, never two pending runs of one app at once (GitHub keeps only one pending run per concurrency group).

The label is added with the PAT, not the Actions token: events made by the Actions token do not start workflows.

Commands (env: GH_TOKEN, FACTORY_PAT, FACTORY_REPO, ISSUE_NUMBER, ISSUE_BODY, RUN_URL):
  start     validate the issue, label it app:<slug>, dispatch the Build Run
  advance   after a child's Build Run succeeded: release its dependents
"""
import json
import os
import re
import subprocess
import sys

GO = "proceed-with-change"
FORM_LABEL = "update-intake"
WAIT = "waiting-on-plan"
APP_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
META_RE = re.compile(r"<!-- factory-plan:(.*?) -->", re.S)


# --- pure logic (unit-tested) -------------------------------------------------


def form_section(body, heading):
    """Text under `### <heading>` in an Issue Form body, surrounding blanks trimmed."""
    out, on = [], False
    for line in (body or "").replace("\r", "").split("\n"):
        if line == f"### {heading}":
            on = True
        elif line.startswith("### "):
            on = False
        elif on:
            out.append(line)
    return "\n".join(out).strip()


def app_name(body):
    """The Managed App named in the form, or ValueError."""
    name = form_section(body, "App name")
    if not name or name == "_No response_":
        raise ValueError('the "App name" field is empty')
    if not APP_RE.fullmatch(name) or len(name) > 30:
        raise ValueError(f"`{name}` is not a Managed App name (lowercase letters, digits and single hyphens, at most 30 characters)")
    return name


def is_factory_repo(description, factory_repo):
    """True only for a repo App Staging created: its description carries `Intake: <factory repo>#<n>`."""
    return bool(re.match(rf"^Intake: {re.escape(factory_repo)}#\d+$", (description or "").strip()))


def plan_meta(body):
    """The plan metadata hidden in a child issue's body ({} for any other issue)."""
    m = META_RE.search(body or "")
    if not m:
        return {}
    try:
        meta = json.loads(m.group(1))
        return meta if isinstance(meta, dict) else {}
    except ValueError:
        return {}


def one_line(text, limit=80):
    return " ".join(str(text).split())[:limit]


def render_change_set_task(cs, request=None, parent=None):
    """The task text for one change set: what the coder, tester and reviewer are given as the spec."""
    lines = [f"Change set {cs['id']}: {cs['title']}", ""]
    if parent:
        lines += [f"Part of a larger request, planned in #{parent}. Do only this change set.", ""]
    if request:
        lines += ["The original request, for context only (do just this change set):", "", request.strip(), ""]
    lines += ["Acceptance criteria:"] + [f"- {c}" for c in cs.get("criteria", [])]
    lines += ["", "How each will be checked:"] + [f"- {v}" for v in cs.get("verification", [])]
    if cs.get("out_of_scope"):
        lines += ["", "Out of scope:"] + [f"- {o}" for o in cs["out_of_scope"]]
    if cs.get("flag"):
        lines += ["", f"Put the whole change behind one feature flag with the slug `{cs['flag']}`."]
    else:
        lines += ["", "Users cannot see or reach any difference from this change, so it needs no flag."]
    return "\n".join(lines).strip()


def child_body(app, task, parent, cs_id, depends_on):
    """A child issue's body: the Update Intake form fields plus hidden plan metadata."""
    meta = {"parent": parent, "cs": cs_id, "depends_on": depends_on}
    # The metadata goes first: text after the last "### " heading would be read as part of that field.
    return (f"<!-- factory-plan:{json.dumps(meta, separators=(',', ':'))} -->\n\n"
            f"### App name\n\n{app}\n\n### What should change?\n\n{task}\n\n### Cost cap override (USD)\n\n_No response_\n")


def ready_to_start(children):
    """The number of the one child to start now, as a list (empty when none). Each child is {number, state, labels,
    depends_on}. It must be open, waiting, not already started, with every issue it depends on closed (an unknown
    dependency counts as open). At most one is started, and none while another is open with `proceed-with-change`:
    one app runs one Build Run at a time, and GitHub drops all but one pending run, so two started together would lose one."""
    if any(c["state"].upper() == "OPEN" and GO in c["labels"] for c in children):
        return []
    state = {c["number"]: c["state"].upper() for c in children}
    ready = [c["number"] for c in children
             if c["state"].upper() == "OPEN" and WAIT in c["labels"]
             and all(state.get(d) == "CLOSED" for d in c["depends_on"])]
    return sorted(ready)[:1]


# --- GitHub (not unit-tested) -------------------------------------------------


def gh(args, token, check=False):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, env={**os.environ, "GH_TOKEN": token})
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {p.stderr.strip()[:200]}")
    return p


def ensure_label(repo, name, token, color="0e8a16", description=""):
    gh(["label", "create", name, "--repo", repo, "--color", color, "--description", description], token)


def file_children(repo, pat, app, parent, change_sets, order, request):
    """Create one issue per change set, dependencies first, and start those with nothing to wait for.
    Returns [(change set id, issue number)]."""
    for name, color, desc in ((FORM_LABEL, "1d76db", "A change request for an existing Managed App"),
                              (WAIT, "fbca04", "Waiting for an earlier change set of the same plan"),
                              (GO, "0e8a16", "Start this change now"), (f"app:{app}", "1d76db", f"Issues about the Managed App {app}"),
                              (f"plan:{parent}", "ededed", f"Change sets planned in #{parent}")):
        ensure_label(repo, name, pat, color, desc)
    by_id = {cs["id"]: cs for cs in change_sets}
    numbers, made = {}, []
    for cs_id in order:
        cs = by_id[cs_id]
        deps = [numbers[d] for d in cs.get("depends_on") or []]
        task = render_change_set_task(cs, parent=parent)
        out = gh(["issue", "create", "--repo", repo, "--title", f"{app}: {one_line(cs['title'])}", "--body", child_body(app, task, parent, cs_id, deps),
                  "--label", f"{FORM_LABEL},app:{app},plan:{parent},{WAIT}"], pat, check=True).stdout
        m = re.search(r"/issues/(\d+)", out)
        numbers[cs_id] = int(m.group(1))
        made.append((cs_id, numbers[cs_id]))
    # Start the first one with nothing to wait for. Done last, so every child exists before the first run begins; the
    # rest are started one at a time by `advance` as each finishes.
    first = next((cs_id for cs_id in order if not by_id[cs_id].get("depends_on")), None)
    if first:
        gh(["issue", "edit", str(numbers[first]), "--repo", repo, "--remove-label", WAIT, "--add-label", GO], pat)
    return made


def siblings(repo, pat, parent):
    out = gh(["issue", "list", "--repo", repo, "--label", f"plan:{parent}", "--state", "all", "--limit", "100",
              "--json", "number,state,labels,body"], pat).stdout
    return [{"number": i["number"], "state": i["state"], "labels": {l["name"] for l in i["labels"]},
             "depends_on": plan_meta(i["body"]).get("depends_on", [])} for i in json.loads(out or "[]")]


def advance(repo, pat, number):
    """After child #number's Build Run succeeded and its issue is closed: start the siblings it was holding up."""
    body = json.loads(gh(["issue", "view", str(number), "--repo", repo, "--json", "body"], pat).stdout or "{}").get("body", "")
    parent = plan_meta(body).get("parent")
    if not parent:
        return []
    started = ready_to_start(siblings(repo, pat, parent))
    for n in started:
        gh(["issue", "edit", str(n), "--repo", repo, "--remove-label", WAIT, "--add-label", GO], pat)
    return started


def start():
    repo, pat, token = os.environ["FACTORY_REPO"], os.environ["FACTORY_PAT"], os.environ["GH_TOKEN"]
    number, body, run_url = os.environ["ISSUE_NUMBER"], os.environ.get("ISSUE_BODY", ""), os.environ.get("RUN_URL", "")
    owner = repo.split("/")[0]

    def refuse(why):
        gh(["issue", "comment", number, "--repo", repo, "--body",
            f"**Update Intake stopped:** {why}\n\nFix this, then add the `{GO}` label again to start. ([run]({run_url}))"], token)
        gh(["issue", "edit", number, "--repo", repo, "--remove-label", GO], token)
        print(f"::error::{why}")
        return 1

    try:
        app = app_name(body)
    except ValueError as e:
        return refuse(str(e))
    if not form_section(body, "What should change?") or form_section(body, "What should change?") == "_No response_":
        return refuse('the "What should change?" field is empty.')
    info = gh(["api", f"repos/{owner}/{app}"], pat)
    if info.returncode != 0:
        return refuse(f"`{owner}/{app}` does not exist. An update Intake changes an app the Factory already built; a new app starts with an Intake.")
    if not is_factory_repo(json.loads(info.stdout).get("description"), repo):
        return refuse(f"`{owner}/{app}` was not created by this Factory (its description is not an `Intake: {repo}#<n>` marker), so the Factory will not change it.")
    ensure_label(repo, f"app:{app}", pat, "1d76db", f"Issues about the Managed App {app}")
    gh(["issue", "edit", number, "--repo", repo, "--add-label", f"app:{app}"], pat, check=True)
    gh(["workflow", "run", "build-run.yml", "--repo", repo, "-f", f"issue_number={number}", "-f", f"app_name={app}"], pat, check=True)
    gh(["issue", "comment", number, "--repo", repo, "--body",
        f"**Update Intake accepted.** A Build Run for `{app}` has been dispatched: it plans the change, then codes, tests and reviews it, "
        f"and releases it behind its flag only when everything passes. ([run]({run_url}))"], token)
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "start":
        return start()
    if cmd == "advance":
        started = advance(os.environ["FACTORY_REPO"], os.environ["FACTORY_PAT"], os.environ["ISSUE_NUMBER"])
        print("started:", started)
        return 0
    print("usage: update_intake.py start|advance", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
