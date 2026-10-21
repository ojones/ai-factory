import json
import os
import sys

from planning import plan_run
from shared import config, github

from factory_change import file_change, pause, prove_reproduction, stop, tiers


def ticket_refusal(body, factory_dir, max_criteria):
    problems = file_change.ticket_problems(body, max_criteria)
    reproduction = file_change.reproduction_of(body)
    if not problems and reproduction.lower() != file_change.NO_REPRODUCTION:
        problems = [prove_reproduction.failure_on_main(factory_dir, reproduction)]
    return "; ".join(p for p in problems if p) or None


def read_ticket(repo, token, number):
    return json.loads(github.run(["issue", "view", str(number), "--repo", repo, "--json", "body"], token).stdout or "{}").get("body") or ""


def gate(repo, token, number, factory_dir, max_criteria):
    if pause.is_paused(repo, token):
        return stop.end(repo, token, number, stop.PAUSED, "the Factory Change process is paused until a person clears the `factory-change-paused` issue")
    refusal = ticket_refusal(read_ticket(repo, token, number), factory_dir, max_criteria)
    return stop.end(repo, token, number, stop.REFUSED, refusal + ". No Agent was run; fix the ticket, then remove the `factory-change` label and add it again.") if refusal else None


def main():
    env = os.environ
    cfg = config.load()
    limits = cfg["limits"]
    stopped = gate(env["GITHUB_REPOSITORY"], env["FACTORY_PAT"], env["ISSUE_NUMBER"], config.FACTORY_DIR, int(limits.get("planner_max_criteria", 6)))
    if stopped:
        return 0
    return plan_run.Planning(env, {"tier_two_paths": tiers.tier_two_paths_text()}).execute()


if __name__ == "__main__":
    sys.exit(main())
