# The planning process (STEP 2.1 to 2.5): read an Intake, ask the planner Agent for a plan, check it, and file one child ticket per change set. It is
# its own workflow (`plan.yml`), started by the Intake's label, before any code is written, and it files at least one child. `PlanRun` is the
# sequencing over parts that are tested alone (validate_plan, triage, secrets_check, render_child, file_children); everything it touches in the
# world (the Agent, GitHub, the clock) is handed in, so each ending is tested without any of them.
#
# Endings: planned (children filed), refused (the Factory cannot build it), awaiting_secret (the owner sets secrets, then re-adds the label),
# needs_human (a blocking question, a rejected plan, a request that cannot be read), skipped (a child ticket, or an Intake already planned). Every
# ending but planned and skipped comments on the Intake and leaves it as it was: retry = edit the issue, remove its label, add it again.
#
# Usage: python -m planning.plan_run   (PYTHONPATH=orchestrator; env as set by .github/workflows/plan.yml)
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from request import check_target_app, intake_labels, read_form
from shared import (
    agent_output,
    agent_runner,
    child_tickets,
    config,
    github,
    prompts,
    provider,
    run_stops,
    spend_budget,
    spend_ledger,
)
from shared.console import log
from shared.shell import sh

from planning import file_children, fix_for, plan_comment, secrets_check, secrets_marker, triage, validate_plan

PLANNED, REFUSED, AWAITING_SECRET, NEEDS_HUMAN, SKIPPED = "planned", "refused", "awaiting_secret", "needs_human", "skipped"
ANSWERED = (PLANNED, SKIPPED, REFUSED, AWAITING_SECRET)  # a workflow that ends this way succeeded; only needs_human is red


class Stop(Exception):
    def __init__(self, ending, message):
        super().__init__(message)
        self.ending = ending


def read_intake(issue, repo, repo_info, limits):
    # What the Intake asks for, or Stop. `repo_info(app)` is the GitHub API answer for the app's repository (a process with returncode and stdout).
    labels = {x["name"] for x in issue.get("labels") or []}
    body = issue.get("body") or ""
    if child_tickets.read_marker(body):
        raise Stop(SKIPPED, "this is a child ticket of a plan, not an Intake")
    if intake_labels.UPDATE_APP_INTAKE in labels:
        kind = "update"
    elif intake_labels.NEW_APP_INTAKE in labels:
        kind = "new"
    else:
        raise Stop(SKIPPED, "this issue is not an Intake")
    found = triage.find_secrets(body)
    if found:
        raise Stop(REFUSED, triage.secret_refusal(found))
    try:
        app = read_form.app_name(body) if kind == "update" else issue["title"].strip()
        if kind == "new" and not read_form.APP_RE.fullmatch(app):
            raise ValueError(f"the issue title `{app}` is not a Managed App name (lowercase letters, digits and single hyphens)")
        task, cap = read_form.read_request(body, limits["cost_cap_usd_default"], limits["cost_cap_usd_ceiling"])
    except ValueError as e:
        raise Stop(NEEDS_HUMAN, str(e))
    if kind == "update":
        info = repo_info(app)
        if info.returncode != 0:
            raise Stop(NEEDS_HUMAN, f"`{app}` does not exist. An update Intake changes an app the Factory already built; a new app starts with an Intake.")
        if not check_target_app.is_factory_repo(json.loads(info.stdout).get("description"), repo):
            raise Stop(NEEDS_HUMAN, f"`{app}` was not created by this Factory (its description is not an `Intake: {repo}#<n>` marker), so the Factory will not change it.")
    raw_cap = read_form.form_section(body, "Cost cap override (USD)").lstrip("$")
    return {"kind": kind, "app": app, "task": task, "cap": cap, "fix_for": child_tickets.read_fix_for(body) or None, "inherit": [x for x in sorted(labels) if x in file_children.INHERITED], "cap_override": raw_cap if raw_cap and raw_cap != read_form.NO_ANSWER else None,
            "declared": secrets_marker.declared_secrets(issue), "label": intake_labels.UPDATE_APP_INTAKE if kind == "update" else intake_labels.NEW_APP_INTAKE}


class PlanRun:
    # `ask(task)` runs the planner and returns (plan document, cost, usage), raising NeedsHuman when no valid plan comes back; `comment(text)` posts on the
    # Intake; `secret_names()` is the set of secrets the app's repo has; `tickets` is the parent's ChildTickets; `file(...)` is file_children.
    def __init__(self, number, intake, limits, ask, comment, secret_names, tickets, file, repo="o/f", pat=""):
        self.number, self.intake, self.lim = int(number), intake, limits
        self.ask, self.comment, self.secret_names, self.tickets, self.file = ask, comment, secret_names, tickets, file
        self.repo, self.pat = repo, pat
        self.cost = 0.0

    def stop(self, ending, message):
        retry = (f"\n\nChange the issue if the request needs to change, then remove the `{self.intake['label']}` label and add it again to plan it again.")
        self.comment(f"**Planning stopped ({ending.replace('_', ' ')}):** {message}{retry}")
        return {"ending": ending, "message": message, "cost": self.cost, "children": []}

    def run(self):
        if self.tickets.children():
            return {"ending": SKIPPED, "message": "this Intake already has child tickets, so it is already planned", "cost": 0.0, "children": []}
        kind = self.intake["kind"]
        build_kind = "update" if kind == "update" else "first build"
        declared = self.intake["declared"]
        if declared:  # checked before the planner is paid for, on every planning
            missing = secrets_check.missing_secrets(declared, self.secret_names())
            if missing:
                return self.stop(AWAITING_SECRET, secrets_check.waiting_message(missing, self.intake["app"], "re-add the label"))
        try:
            doc, self.cost, _usage = self.ask(fix_for.task_for(self.intake["task"], self.intake.get("fix_for")))
        except run_stops.NeedsHuman as e:
            return self.stop(NEEDS_HUMAN, str(e))
        blocked, category, reasons, possible = triage.feasibility(doc)
        if blocked:
            return self.stop(REFUSED, triage.refusal_text(category, reasons, possible))
        problems, questions = validate_plan.validate_plan(doc, build_kind, fix_for.max_change_sets(self.intake.get("fix_for"), int(self.lim.get("planner_max_change_sets", validate_plan.MAX_CHANGE_SETS))),
                                                          int(self.lim.get("planner_max_criteria", validate_plan.MAX_CRITERIA)))
        if problems:
            return self.stop(NEEDS_HUMAN, "the planner's plan was rejected: " + "; ".join(problems))
        if questions:
            self.comment(plan_comment.render_plan_comment(doc, questions))
            return self.stop(NEEDS_HUMAN, "the plan needs a person to answer first: " + " | ".join(questions))
        needed = [x for x in doc.get("secrets") or [] if isinstance(x, dict)]
        if needed:
            missing = secrets_check.missing_secrets(needed, self.secret_names())
            self.comment(secrets_check.request_comment(needed, missing, self.intake["app"]))
            if missing:
                return {"ending": AWAITING_SECRET, "message": secrets_check.waiting_message(missing, self.intake["app"], "re-add the label"),
                        "cost": self.cost, "children": []}
        sets = doc["change_sets"]
        made = self.file(self.number, sets, validate_plan.topological_order(sets), needed, **({"fix": self.intake["fix_for"]} if self.intake.get("fix_for") else {}))
        lines = ", ".join(f"{cs} (#{n})" for cs, n in made)
        self.comment(plan_comment.render_plan_comment(doc) + f"\n\n**Filed {len(made)} child ticket(s), run one at a time in this order:** {lines}.")
        return {"ending": PLANNED, "message": f"Planned as {len(made)} change set(s): {lines}.", "cost": self.cost, "children": made}


def seed_workdir(app_dir, starter=None):
    # A new app has no code yet, so the planner reads the Starter Template it will start from (a copy, so reading it changes nothing): the same AGENTS.md, flag client and
    # routes the coder will find. Without it the planner asked people questions the code answers (found by the second and third live planning).
    starter = Path(starter or config.FACTORY_DIR / "templates" / "starter")
    shutil.copytree(starter, app_dir, ignore=shutil.ignore_patterns("node_modules", ".git", "dist", "build"), dirs_exist_ok=True)


def available_model(cfg, role, key):
    # The role's model, or its fallback when the provider no longer serves it; NeedsHuman when neither is served.
    profile = cfg["roles"][role]
    base = cfg["provider"]["base_url"]
    if provider.model_status(base, key, profile["model"]) != "missing":
        return
    fallback = profile.get("fallback_model")
    if not fallback or provider.model_status(base, key, fallback) == "missing":
        raise run_stops.NeedsHuman("other", f"the {role} model `{profile['model']}` is no longer served and "
                                   + ("its fallback is not either" if fallback else "the role has no fallback_model") + ": choose a model in agents/profiles.yml")
    log(f"{role}: `{profile['model']}` is not served; using its fallback `{fallback}`")
    profile["model"] = fallback


def main():
    e = os.environ
    repo, number = e["GITHUB_REPOSITORY"], e["ISSUE_NUMBER"]
    pat, token = e["FACTORY_PAT"], e["FACTORY_GH_TOKEN"]
    cfg = config.load()
    lim = cfg["limits"]
    if not lim.get("planner_enabled", True):
        log("planning is switched off (limits.planner_enabled)")
        return 0

    def gh(args, tok=None):
        return github.run(args, tok or token)

    issue = json.loads(gh(["issue", "view", number, "--repo", repo, "--json", "title,body,labels,comments"]).stdout)
    owner = repo.split("/")[0]
    try:
        intake = read_intake(issue, repo, lambda app: gh(["api", f"repos/{owner}/{app}"], pat), lim)
    except Stop as s:
        if s.ending == SKIPPED:
            log(f"skipped: {s}")
            return 0
        gh(["issue", "comment", number, "--repo", repo, "--body", f"**Planning stopped ({s.ending.replace('_', ' ')}):** {s}"])
        return 0 if s.ending in ANSWERED else 1
    work = Path(e.get("BUILD_RUN_DIR") or tempfile.mkdtemp(prefix="plan-"))
    app_dir, art = Path(e.get("APP_DIR") or work / "app"), work / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    agent_user = e.get("AGENT_USER") or None
    app_repo = f"{owner}/{intake['app']}"
    run = None
    try:
        daily = float(lim.get("daily_cost_cap_usd", 0) or 0)
        spent_today = spend_ledger.todays_spend(lambda args, tok: gh(args, tok), repo, token) if daily > 0 else None
        if spent_today is not None and spent_today >= daily:
            raise run_stops.NeedsHuman("other", f"today's Build Runs have already spent ${spent_today:.2f} of the ${daily:.2f} daily cap; try again tomorrow")
        key = e["DEEPINFRA_API_KEY"]
        available_model(cfg, "planner", key)
        budget = spend_budget.Budget(key, float(lim.get("planner_cost_cap_usd", 0.5)), lim["jwt_ttl_seconds"])
        if intake["kind"] == "update":
            auth = github.git_auth_env("Authorization: Basic " + base64.b64encode(f"x-access-token:{pat}".encode()).decode())
            sh(["git", "clone", "-q", f"https://github.com/{app_repo}.git", str(app_dir)], env={**os.environ, **auth})
            if agent_user:
                sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{agent_user}:rwX,u:{e.get('USER', 'runner')}:rwX", str(app_dir)], check=False)
        else:
            seed_workdir(app_dir)
            if agent_user:
                sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{agent_user}:rwX,u:{e.get('USER', 'runner')}:rwX", str(app_dir)], check=False)
        runner = agent_runner.AgentRunner(cfg, budget, art, work, app_dir, agent_user, on_spend=lambda jwt: round(budget.refresh(jwt), 6))
        path = work / "plan.json"

        def restore(cwd=None):
            if intake["kind"] == "update" and sh(["git", "status", "--porcelain"], cwd=app_dir, check=False).stdout.strip():
                sh(["git", "reset", "-q", "--hard", "HEAD"], cwd=app_dir, check=False)
                sh(["git", "clean", "-fdq"], cwd=app_dir, check=False)

        build_kind = "update" if intake["kind"] == "update" else "first build"
        problems = []

        def check(doc):
            found, _ = validate_plan.validate_plan(doc, build_kind, int(lim.get("planner_max_change_sets", validate_plan.MAX_CHANGE_SETS)),
                                                   int(lim.get("planner_max_criteria", validate_plan.MAX_CRITERIA)))
            problems[:] = found
            if found:
                raise ValueError("; ".join(found))

        def ask(task):
            prompt = prompts.render(prompts.load_prompt(cfg["roles"]["planner"]["prompt"]),
                                    {"app_name": intake["app"], "build_kind": build_kind, "task": task, "plan_path": path, "spec": task})
            return agent_runner.json_output(lambda label, note: runner.run("planner", label, agent_output.retry_prompt(prompt, note)), path, "planner", "1",
                                            lambda r, lab: art / f"openhands-{r}-{lab}.jsonl", None, check, restore=restore)

        tickets = child_tickets.ChildTickets(repo, number, pat)
        run = PlanRun(number, intake, lim, ask, lambda text: gh(["issue", "comment", number, "--repo", repo, "--body", text]),
                      lambda: secret_names_of(app_repo, gh), tickets,
                      lambda parent, sets, order, secrets, fix=None: file_children.file_children(repo, pat, intake["app"], parent, sets, order, intake["task"],
                                                                                                  cap=intake["cap_override"], secrets=secrets, tickets=tickets, fix=fix, inherit=intake["inherit"]),
                      repo, pat)
        result = run.run()
    except run_stops.ProviderBlocked as e:
        result = {"ending": NEEDS_HUMAN, "message": str(e) or provider.BLOCKED_MESSAGE, "cost": 0.0, "children": []}
        gh(["issue", "comment", number, "--repo", repo, "--body", f"**Planning stopped:** {result['message']}"])
    except (run_stops.NeedsHuman, run_stops.BudgetExhausted, child_tickets.ChildTicketError, secrets_check.SecretsUnreadable) as e:
        result = {"ending": NEEDS_HUMAN, "message": str(e), "cost": 0.0, "children": []}
        gh(["issue", "comment", number, "--repo", repo, "--body",
            f"**Planning stopped (needs human):** {e}\n\nThen remove the `{intake['label']}` label and add it again to plan it again."])
    spent = result["cost"] or (run.cost if run else 0.0)
    if spent:
        spend_ledger.record_spend_in_ledger({"app": intake["app"], "spent_usd": spent}, repo, f"{e.get('GITHUB_RUN_ID', '0')}-plan", token)
    log(f"planning ended {result['ending']}: {result['message']}")
    with open(e.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as f:
        f.write(f"## Planning: {result['ending']}\n\n{result['message']}\n")
    return 0 if result["ending"] in ANSWERED else 1


def secret_names_of(app_repo, gh):
    return secrets_check.present_names(lambda args: gh(args), app_repo)


if __name__ == "__main__":
    sys.exit(main())
