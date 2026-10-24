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
ANSWERED = (PLANNED, SKIPPED, REFUSED, AWAITING_SECRET)


class Stop(Exception):
    def __init__(self, ending, message):
        super().__init__(message)
        self.ending = ending


def intake_kind(labels, body):
    if child_tickets.read_marker(body):
        raise Stop(SKIPPED, "this is a child ticket of a plan, not an Intake")
    if intake_labels.UPDATE_APP_INTAKE in labels:
        return "update"
    if intake_labels.NEW_APP_INTAKE in labels:
        return "new"
    raise Stop(SKIPPED, "this issue is not an Intake")


BUILD_KINDS = {"update": "update", "new": "first build"}


def read_request_or_stop(kind, issue, body, limits):
    try:
        app = read_form.app_name(body) if kind == "update" else issue["title"].strip()
        if kind == "new" and not read_form.APP_RE.fullmatch(app):
            raise ValueError(f"the issue title `{app}` is not a Managed App name (lowercase letters, digits and single hyphens)")
        task, cap = read_form.read_request(body, limits["cost_cap_usd_default"], limits["cost_cap_usd_ceiling"])
    except ValueError as e:
        raise Stop(NEEDS_HUMAN, str(e))
    return app, task, cap


def require_factory_app(app, repo, repo_info):
    info = repo_info(app)
    if info.returncode != 0:
        raise Stop(NEEDS_HUMAN, f"`{app}` does not exist. An update Intake changes an app the Factory already built; a new app starts with an Intake.")
    if not check_target_app.is_factory_repo(json.loads(info.stdout).get("description"), repo):
        raise Stop(NEEDS_HUMAN, f"`{app}` was not created by this Factory (its description is not an `Intake: {repo}#<n>` marker), so the Factory will not change it.")


def requested_cap_override(body):
    raw_cap = read_form.form_section(body, "Cost cap override (USD)").lstrip("$")
    return raw_cap if raw_cap and raw_cap != read_form.NO_ANSWER else None


def read_intake(issue, repo, repo_info, limits):
    labels = {x["name"] for x in issue.get("labels") or []}
    body = issue.get("body") or ""
    kind = intake_kind(labels, body)
    found = triage.find_secrets(body)
    if found:
        raise Stop(REFUSED, triage.secret_refusal(found))
    app, task, cap = read_request_or_stop(kind, issue, body, limits)
    if kind == "update":
        require_factory_app(app, repo, repo_info)
    label = intake_labels.UPDATE_APP_INTAKE if kind == "update" else intake_labels.NEW_APP_INTAKE
    return {"kind": kind, "app": app, "task": task, "cap": cap, "fix_for": child_tickets.read_fix_for(body) or None,
            "inherit": [x for x in sorted(labels) if x in file_children.INHERITED], "cap_override": requested_cap_override(body),
            "declared": secrets_marker.declared_secrets(issue), "label": label}


def planner_max_change_sets(limits, fix):
    return fix_for.max_change_sets(fix, int(limits.get("planner_max_change_sets", validate_plan.MAX_CHANGE_SETS)))


def planner_max_criteria(limits):
    return int(limits.get("planner_max_criteria", validate_plan.MAX_CRITERIA))


def declared_secret_dicts(doc):
    return [x for x in doc.get("secrets") or [] if isinstance(x, dict)]


class PlanRun:
    def __init__(self, number, intake, limits, ask, comment, secret_names, tickets, file, repo="o/f", pat=""):
        self.number, self.intake, self.lim = int(number), intake, limits
        self.ask, self.comment, self.secret_names, self.tickets, self.file = ask, comment, secret_names, tickets, file
        self.repo, self.pat = repo, pat
        self.cost = 0.0

    def ended(self, ending, message, children=()):
        return {"ending": ending, "message": message, "cost": self.cost, "children": list(children)}

    def stop(self, ending, message):
        retry = (f"\n\nChange the issue if the request needs to change, then remove the `{self.intake['label']}` label and add it again to plan it again.")
        self.comment(f"**Planning stopped ({ending.replace('_', ' ')}):** {message}{retry}")
        return self.ended(ending, message)

    def run(self):
        if self.tickets.children():
            return self.ended(SKIPPED, "this Intake already has child tickets, so it is already planned")
        return self.waiting_for_declared_secrets() or self.plan_and_file()

    def waiting_message(self, missing):
        return secrets_check.waiting_message(missing, self.intake["app"], "re-add the label")

    def waiting_for_declared_secrets(self):
        declared = self.intake["declared"]
        missing = secrets_check.missing_secrets(declared, self.secret_names()) if declared and self.intake["kind"] != "new" else []
        return self.stop(AWAITING_SECRET, self.waiting_message(missing)) if missing else None

    def plan_and_file(self):
        try:
            doc, self.cost, _usage = self.ask(fix_for.task_for(self.intake["task"], self.intake.get("fix_for")))
        except run_stops.NeedsHuman as e:
            return self.stop(NEEDS_HUMAN, str(e))
        return self.rejected(doc) or self.asking_for_secrets(doc) or self.file_children_and_report(doc)

    def validate(self, doc):
        fix = self.intake.get("fix_for")
        return validate_plan.validate_plan(doc, BUILD_KINDS[self.intake["kind"]], planner_max_change_sets(self.lim, fix), planner_max_criteria(self.lim))

    def rejected(self, doc):
        blocked, category, reasons, possible = triage.feasibility(doc)
        if blocked:
            return self.stop(REFUSED, triage.refusal_text(category, reasons, possible))
        problems, questions = self.validate(doc)
        if problems:
            return self.stop(NEEDS_HUMAN, "the planner's plan was rejected: " + "; ".join(problems))
        if questions:
            self.comment(plan_comment.render_plan_comment(doc, questions))
            return self.stop(NEEDS_HUMAN, "the plan needs a person to answer first: " + " | ".join(questions))

    def asking_for_secrets(self, doc):
        needed = declared_secret_dicts(doc)
        if not needed:
            return None
        if self.intake["kind"] == "new":
            self.comment(secrets_check.new_app_comment(needed, self.intake["app"]))
            return None
        missing = secrets_check.missing_secrets(needed, self.secret_names())
        self.comment(secrets_check.request_comment(needed, missing, self.intake["app"]))
        return self.ended(AWAITING_SECRET, self.waiting_message(missing)) if missing else None

    def file_children_and_report(self, doc):
        sets = doc["change_sets"]
        fix = {"fix": self.intake["fix_for"]} if self.intake.get("fix_for") else {}
        made = self.file(self.number, sets, validate_plan.topological_order(sets), declared_secret_dicts(doc), **fix)
        lines = ", ".join(f"{cs} (#{n})" for cs, n in made)
        self.comment(plan_comment.render_plan_comment(doc) + f"\n\n**Filed {len(made)} child ticket(s), run one at a time in this order:** {lines}.")
        return self.ended(PLANNED, f"Planned as {len(made)} change set(s): {lines}.", made)


def seed_workdir(app_dir, starter=None):
    starter = Path(starter or config.FACTORY_DIR / "templates" / "starter")
    shutil.copytree(starter, app_dir, ignore=shutil.ignore_patterns("node_modules", ".git", "dist", "build"), dirs_exist_ok=True)


def available_model(cfg, role, key):
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


class PlannerAsk:
    def __init__(self, cfg, intake, runner, work, art, app_dir):
        self.cfg, self.intake, self.runner, self.art, self.app_dir = cfg, intake, runner, art, app_dir
        self.path = work / "plan.json"
        self.build_kind = BUILD_KINDS[intake["kind"]]
        self.role = "planner"

    def restore(self, cwd=None):
        if self.intake["kind"] == "new" or not sh(["git", "status", "--porcelain"], cwd=self.app_dir, check=False).stdout.strip():
            return
        sh(["git", "reset", "-q", "--hard", "HEAD"], cwd=self.app_dir, check=False)
        sh(["git", "clean", "-fdq"], cwd=self.app_dir, check=False)

    def check(self, doc):
        lim = self.cfg["limits"]
        found, _ = validate_plan.validate_plan(doc, self.build_kind, planner_max_change_sets(lim, None), planner_max_criteria(lim))
        if found:
            raise ValueError("; ".join(found))

    def prompt(self, task):
        values = {"app_name": self.intake["app"], "build_kind": self.build_kind, "task": task, "plan_path": self.path, "spec": task}
        return prompts.render(prompts.load_prompt(self.cfg["roles"][self.role]["prompt"]), values)

    def __call__(self, task):
        prompt = self.prompt(task)
        run_agent = lambda label, note: self.runner.run(self.role, label, agent_output.retry_prompt(prompt, note))
        log_path = lambda r, lab: self.art / f"openhands-{r}-{lab}.jsonl"
        return agent_runner.json_output(run_agent, self.path, self.role, "1", log_path, None, self.check, restore=self.restore)


def share_with_agent(path, agent_user):
    if agent_user:
        sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{agent_user}:rwX,u:{os.environ.get('USER', 'runner')}:rwX", str(path)], check=False)


def clone_app(app_repo, app_dir, pat):
    auth = github.git_auth_env("Authorization: Basic " + base64.b64encode(f"x-access-token:{pat}".encode()).decode())
    sh(["git", "clone", "-q", f"https://github.com/{app_repo}.git", str(app_dir)], env={**os.environ, **auth})


class Planning:
    def __init__(self, env):
        self.env = env
        self.repo, self.number = env["GITHUB_REPOSITORY"], env["ISSUE_NUMBER"]
        self.pat, self.token = env["FACTORY_PAT"], env["FACTORY_GH_TOKEN"]
        self.cfg = config.load()
        self.lim = self.cfg["limits"]
        self.owner = self.repo.split("/")[0]
        self.run = None

    def gh(self, args, tok=None):
        return github.run(args, tok or self.token)

    def comment(self, text):
        self.gh(["issue", "comment", self.number, "--repo", self.repo, "--body", text])

    def read_intake(self):
        issue = json.loads(self.gh(["issue", "view", self.number, "--repo", self.repo, "--json", "title,body,labels,comments"]).stdout)
        return read_intake(issue, self.repo, lambda app: self.gh(["api", f"repos/{self.owner}/{app}"], self.pat), self.lim)

    def report_unreadable(self, stop):
        if stop.ending == SKIPPED:
            log(f"skipped: {stop}")
            return 0
        self.comment(f"**Planning stopped ({stop.ending.replace('_', ' ')}):** {stop}")
        return 0 if stop.ending in ANSWERED else 1

    def check_daily_cap(self):
        daily = float(self.lim.get("daily_cost_cap_usd", 0) or 0)
        spent_today = spend_ledger.todays_spend(lambda args, tok: self.gh(args, tok), self.repo, self.token) if daily > 0 else None
        if spent_today is not None and spent_today >= daily:
            raise run_stops.NeedsHuman("other", f"today's Build Runs have already spent ${spent_today:.2f} of the ${daily:.2f} daily cap; try again tomorrow")

    def checkout(self, app_dir, app_repo, agent_user):
        if self.intake["kind"] == "update":
            clone_app(app_repo, app_dir, self.pat)
        else:
            seed_workdir(app_dir)
        share_with_agent(app_dir, agent_user)

    def build_run(self):
        self.check_daily_cap()
        key = self.env["DEEPINFRA_API_KEY"]
        available_model(self.cfg, "planner", key)
        budget = spend_budget.Budget(key, float(self.lim.get("planner_cost_cap_usd", 0.5)), self.lim["jwt_ttl_seconds"])
        work = Path(self.env.get("BUILD_RUN_DIR") or tempfile.mkdtemp(prefix="plan-"))
        app_dir, art = Path(self.env.get("APP_DIR") or work / "app"), work / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        agent_user = self.env.get("AGENT_USER") or None
        app_repo = f"{self.owner}/{self.intake['app']}"
        self.checkout(app_dir, app_repo, agent_user)
        runner = agent_runner.AgentRunner(self.cfg, budget, art, work, app_dir, agent_user, on_spend=lambda jwt: round(budget.refresh(jwt), 6))
        ask = PlannerAsk(self.cfg, self.intake, runner, work, art, app_dir)
        return self.plan_run(ask, app_repo)

    def plan_run(self, ask, app_repo):
        tickets = child_tickets.ChildTickets(self.repo, self.number, self.pat)
        intake = self.intake

        def file(parent, sets, order, secrets, fix=None):
            return file_children.file_children(self.repo, self.pat, intake["app"], parent, sets, order, intake["task"],
                                               cap=intake["cap_override"], secrets=secrets, tickets=tickets, fix=fix, inherit=intake["inherit"])
        return PlanRun(self.number, intake, self.lim, ask, self.comment, lambda: secret_names_of(app_repo, self.gh), tickets, file, self.repo, self.pat)

    def plan(self):
        try:
            self.run = self.build_run()
            return self.run.run()
        except run_stops.ProviderBlocked as e:
            message = str(e) or provider.BLOCKED_MESSAGE
            self.comment(f"**Planning stopped:** {message}")
            return {"ending": NEEDS_HUMAN, "message": message, "cost": 0.0, "children": []}
        except (run_stops.NeedsHuman, run_stops.BudgetExhausted, child_tickets.ChildTicketError, secrets_check.SecretsUnreadable) as e:
            self.comment(f"**Planning stopped (needs human):** {e}\n\nThen remove the `{self.intake['label']}` label and add it again to plan it again.")
            return {"ending": NEEDS_HUMAN, "message": str(e), "cost": 0.0, "children": []}

    def record(self, result):
        spent = result["cost"] or (self.run.cost if self.run else 0.0)
        if spent:
            spend_ledger.record_spend_in_ledger({"app": self.intake["app"], "spent_usd": spent}, self.repo, f"{self.env.get('GITHUB_RUN_ID', '0')}-plan", self.token)
        log(f"planning ended {result['ending']}: {result['message']}")
        with open(self.env.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as f:
            f.write(f"## Planning: {result['ending']}\n\n{result['message']}\n")

    def execute(self):
        try:
            self.intake = self.read_intake()
        except Stop as stop:
            return self.report_unreadable(stop)
        result = self.plan()
        self.record(result)
        return 0 if result["ending"] in ANSWERED else 1


def main():
    job = Planning(os.environ)
    if not job.lim.get("planner_enabled", True):
        log("planning is switched off (limits.planner_enabled)")
        return 0
    return job.execute()


def secret_names_of(app_repo, gh):
    return secrets_check.present_names(lambda args: gh(args), app_repo)


if __name__ == "__main__":
    sys.exit(main())
