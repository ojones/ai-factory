import json
import os
import shutil
import sys
from pathlib import Path

from request import read_form
from retrospective import agent_run
from shared import agent_runner, child_tickets, config, github, run_stops, spend_budget, spend_ledger
from shared.console import log
from shared.shell import sh

from factory_change import gate, hold_for_person, open_pr, pause, protection, review_change, stop, tiers, vet_change, write_change

RETRY, REFUSE, DONE, HOLD = "retry", "refuse", "done", "hold"


def finding(summary):
    return {"summary": summary, "evidence": summary, "severity": "blocking"}


def discard_all(factory):
    sh(["git", "reset", "-q", "--hard", "HEAD"], cwd=factory)
    sh(["git", "clean", "-fdq"], cwd=factory)


class ChangeRun:
    def __init__(self, repo, child, pat, cfg, factory, work, runner, budget, task):
        self.repo, self.child, self.pat, self.cfg = repo, child, pat, cfg
        self.factory, self.work, self.runner, self.budget, self.task = Path(factory), Path(work), runner, budget, task
        self.limits = cfg["limits"]
        self.snapshot = None

    def end(self, outcome, why):
        return stop.end(self.repo, self.pat, self.child, outcome, why)

    def take_snapshot(self):
        self.snapshot = self.work / "main-snapshot"
        shutil.rmtree(self.snapshot, ignore_errors=True)
        shutil.copytree(self.factory, self.snapshot, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"), symlinks=True)

    def proof_problem(self, name, changes):
        return gate.named_reproduction_problem(self.snapshot, self.factory, name, changes)

    def tests_problem(self):
        root = agent_run.scratch_root()
        try:
            return None if agent_run.run_tests(self.factory, root, self.runner.agent_user) else "the unit tests fail with this change; run them from the orchestrator folder and fix what fails"
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def scope_problem(self, changes):
        return vet_change.problem(changes, self.limits, vet_change.patches_of(self.factory, changes))

    def attempt(self, round_no, blocking):
        result = write_change.write_change(self.cfg, self.runner, self.factory, self.work, self.task, round_no, blocking)
        if result is None:
            return RETRY, [finding("write the reproduction's test name and a summary to the result file")]
        if result.get("spec_paths"):
            return HOLD, f"this change needs a person to edit {', '.join(result['spec_paths'])}, which no Agent may change; the code is discarded"
        changes = vet_change.read_changes(self.factory)
        why = self.scope_problem(changes)
        if why:
            return REFUSE, why
        why = self.proof_problem(result["reproduction"], changes) or self.tests_problem()
        return (RETRY, [finding(why)]) if why else self.reviewed(result, changes)

    def reviewed(self, result, changes):
        clean, blocking, _ = review_change.review(self.cfg, self.budget, self.factory, self.task)
        return (DONE, (result, changes)) if clean else (RETRY, blocking)

    def rounds(self):
        blocking = []
        for round_no in range(1, int(self.limits["factory_change_review_rounds"]) + 1):
            kind, payload = self.attempt(round_no, blocking)
            if kind != RETRY:
                return kind, payload
            blocking = payload
        return RETRY, "the review rounds are used up and blocking findings remain"

    def deliver(self, result, changes):
        paths = sorted(changes)
        url = open_pr.open_pr(self.factory, self.repo, self.pat, self.child, result.get("summary") or "Factory Change", result["reproduction"], paths,
                              int(self.limits["max_open_factory_change_prs"]))
        if not url:
            return self.end(stop.NEEDS_HUMAN, f"{self.limits['max_open_factory_change_prs']} Factory Change pull requests are already open; close or merge one, then start this again")
        if tiers.merge_tier(paths) == tiers.TIER_TWO:
            return hold_for_person.hold(self.repo, self.pat, self.child, url, paths)
        stop.comment(self.repo, self.pat, self.child, f"Opened {url}. It merges itself once the checks and the gate pass.")
        return stop.OPENED

    def run(self):
        if pause.is_paused(self.repo, self.pat):
            return self.end(stop.PAUSED, "the Factory Change process is paused until a person clears the `factory-change-paused` issue")
        unprotected = protection.problem(self.repo, self.pat)
        if unprotected:
            return self.end(stop.NEEDS_HUMAN, unprotected)
        self.take_snapshot()
        kind, payload = self.rounds()
        if kind == DONE:
            return self.deliver(*payload)
        discard_all(self.factory)
        return self.end(stop.REFUSED if kind == REFUSE else stop.NEEDS_HUMAN, payload)


def daily_cap_reached(limits, repo, token):
    daily = float(limits.get("daily_cost_cap_usd", 0) or 0)
    spent = spend_ledger.todays_spend(github.run, repo, token) if daily > 0 else None
    return spent is not None and spent >= daily


def read_task(repo, token, child):
    issue = json.loads(github.run(["issue", "view", str(child), "--repo", repo, "--json", "body"], token).stdout or "{}")
    body = issue.get("body") or ""
    if child_tickets.read_marker(body).get("kind") != "factory":
        return None
    return read_form.form_section(body, "What should change?").strip()


def build_runner(cfg, budget, work, factory):
    art = Path(work) / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    return agent_runner.AgentRunner(cfg, budget, art, work, factory, os.environ.get("AGENT_USER") or None, on_spend=lambda jwt: round(budget.refresh(jwt), 6))


def execute(env):
    repo, child, pat = env["GITHUB_REPOSITORY"], env["ISSUE_NUMBER"], env["FACTORY_PAT"]
    cfg = config.load()
    task = read_task(repo, pat, child)
    if not task:
        log("not a Factory Change child")
        return None
    if daily_cap_reached(cfg["limits"], repo, pat):
        return stop.end(repo, pat, child, stop.NEEDS_HUMAN, "today's spend has reached the daily cap; try again tomorrow")
    budget = spend_budget.Budget(env["DEEPINFRA_API_KEY"], float(cfg["limits"]["factory_change_cost_cap_usd"]), cfg["limits"]["jwt_ttl_seconds"])
    work = Path(env.get("BUILD_RUN_DIR") or "run")
    work.mkdir(parents=True, exist_ok=True)
    run = ChangeRun(repo, child, pat, cfg, config.FACTORY_DIR, work, build_runner(cfg, budget, work, config.FACTORY_DIR), budget, task)
    try:
        return run.run()
    finally:
        spend_ledger.record_spend_in_ledger({"app": "factory-change", "spent_usd": budget.spent_known()}, repo, f"{env.get('GITHUB_RUN_ID', '0')}-fc", pat)


def main():
    env = os.environ
    try:
        execute(env)
    except (run_stops.NeedsHuman, run_stops.BudgetExhausted, run_stops.ProviderBlocked, RuntimeError) as e:
        stop.end(env["GITHUB_REPOSITORY"], env["FACTORY_PAT"], env["ISSUE_NUMBER"], stop.NEEDS_HUMAN, f"the run stopped: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
