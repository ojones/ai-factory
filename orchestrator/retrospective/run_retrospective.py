import json
import os
import sys
from pathlib import Path

from shared import agent_output, config, outcomes
from shared.console import log
from try_fix import collect_events, file_failure, provider_alert, write_bug

from retrospective import (
    agent_run,
    analysis,
    event_verdicts,
    fix_budget,
    improvement_issues,
    judge_events,
    lesson_records,
    minor_findings,
    run_facts,
    story_report,
)
from retrospective.cause import name_cause


def bugs_today(cfg, repo, token, app):
    try:
        return fix_budget.bugs_filed_today(repo, token, app)
    except Exception as e:  # noqa: BLE001 - counting never fails the run
        log(f"could not count today's bug tickets, so no warning is fixed this run: {type(e).__name__}: {e}")
        return event_verdicts.fix_cap(cfg.get("limits"))


def ask_about_warnings(open_warnings, cfg, key, repo, token):
    agent_key, budget = agent_run.mint_agent(cfg, key)
    if not agent_key:
        return {}
    got = judge_events.answer(open_warnings, cfg, agent_key)
    agent_run.record_agent_spend(budget, agent_key, repo, token, os.environ.get("GITHUB_RUN_ID", "0"))
    return got


def judge_run_events(events, result, cfg, key, repo, token, app, work, outcome):
    entries = event_verdicts.parse(result)
    fixed = bugs_today(cfg, repo, token, app)
    open_warnings = [e for e in events if e["severity"] == "warning" and e["key"] not in entries]
    if open_warnings and key and "retrospective" in cfg.get("roles", {}) and fixed < event_verdicts.fix_cap(cfg.get("limits")):
        entries.update(ask_about_warnings(open_warnings, cfg, key, repo, token))
    verdicts = event_verdicts.decide(events, entries, cfg.get("limits", {}), fixed)
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    (work / "artifacts" / "retrospective-verdicts.json").write_text(json.dumps(verdicts, indent=2))
    if verdicts:
        log("event verdicts:\n" + event_verdicts.render(verdicts))
    return verdicts


class Retrospective:
    def __init__(self, work, d):
        self.work, self.d = work, d
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.pat, self.token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
        self.run_id = os.environ.get("GITHUB_RUN_ID", "0")
        self.stuck = d.get("outcome") not in outcomes.OK
        self.artifacts = work / "artifacts"

    def alert_provider(self):
        try:
            log(f"provider alert: {provider_alert.file_provider_alert(self.repo, self.token, self.facts)}")
        except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
            log(f"could not file the provider alert: {type(e).__name__}: {e}")
        return 0

    def gather(self):
        self.lessons = lesson_records.lessons_from(self.facts)
        self.events = collect_events.from_run(self.facts, run_facts.fingerprint(self.facts))
        self.facts["events"] = self.events
        self.facts["signals"] = [{"kind": x["kind"], "detail": x["detail"]} for x in self.lessons]
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.facts_path = self.artifacts / "retrospective-facts.json"
        self.facts_path.write_text(json.dumps(self.facts, indent=2))

    def record_findings(self):
        minor_findings.record_minors(self.repo, self.token, self.facts)
        self.filed = improvement_issues.record_improvements(self.repo, self.token, self.facts)

    def severe_lessons(self):
        recorded = [(lesson_records.record_lesson(self.repo, self.token, x, self.facts)[0], x["severe"]) for x in self.lessons]
        return [n for n, severe in recorded if n and severe]

    def targets(self):
        outcome = self.d.get("outcome")
        stuck_issue = lesson_records.record_issue(self.repo, self.token, self.facts) if lesson_records.records_stuck_issue(outcome) else None
        self.record_findings()
        return list(dict.fromkeys(([stuck_issue] if stuck_issue else []) + self.severe_lessons()))

    def analyse(self, targets):
        if not (targets and self.key and "retrospective" in self.cfg.get("roles", {})):
            return None
        return analysis.analyse(config.FACTORY_DIR, self.cfg, self.repo, self.token, self.key, self.facts_path, self.work / "retrospective-result.json", targets, self.run_id)

    def file_event_fixes(self, verdicts, result):
        fixes = event_verdicts.fix_events(verdicts)
        if not (fixes and bool(self.cfg.get("limits", {}).get("fix_requests", True))):
            return None
        spend = lambda budget, cred: write_bug.record_spend(budget, cred, self.repo, self.token, self.run_id)
        filed_events = file_failure.file_failures(self.repo, self.token, self.pat, fixes, self.facts, result, self.d.get("rollback"), self.cfg, self.key, spend)
        for got in filed_events:
            log(f"event {got['key']} handled ({got['target']}: {got['action']}) {got['url']}")
        return next((g for g in filed_events if g["severity"] == "failure"), None)

    def note_bugs(self, filed_request):
        if not (self.facts.get("bugs") and self.stuck):
            return []
        try:
            carried = bool(filed_request and filed_request["action"] == "bug_intake")
            if story_report.note_bugs_on_story(self.repo, self.token, self.d["issue_number"], self.facts, carried):
                return [{"kind": x["kind"], "check": x["check"], "url": ""} for x in self.facts["bugs"][:story_report.MAX_BUGS]]
        except Exception as e:  # noqa: BLE001
            log(f"could not note the bugs on the story: {type(e).__name__}: {e}")
        return []

    def post(self, result, cause, verdicts, bugs):
        try:
            body = story_report.render_retrospective(self.facts, self.filed, self.lessons, result, bugs, cause, verdicts)
            story_report.post_retrospective(self.repo, self.token, self.d["issue_number"], self.run_id, body)
        except Exception as e:  # noqa: BLE001
            log(f"could not post the retrospective on the issue: {type(e).__name__}: {e}")

    def run(self):
        if self.d.get("outcome") in outcomes.ANSWERED:
            return 0
        self.facts = run_facts.collect_facts(self.work, self.d)
        if self.d.get("outcome") == "provider_blocked":
            return self.alert_provider()
        self.cfg, self.key = config.load(), os.environ.get("DEEPINFRA_API_KEY")
        self.gather()
        result = self.analyse(self.targets())
        cause = name_cause(self.facts, result)
        verdicts = judge_run_events(self.events, result, self.cfg, self.key, self.repo, self.token, self.d["app"], self.work, self.d.get("outcome"))
        (self.artifacts / "retrospective-cause.json").write_text(json.dumps(cause, indent=2))
        bugs = self.note_bugs(self.file_event_fixes(verdicts, result))
        self.post(result, cause, verdicts, bugs)
        return 0


def main():
    work = Path(os.environ["BUILD_RUN_DIR"])
    d = agent_output.load_json(work / "state.json")
    return Retrospective(work, d).run() if d else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - the retrospective must never fail the run
        print(f"::warning::retrospective failed: {type(e).__name__}: {e}", flush=True)
        sys.exit(0)
