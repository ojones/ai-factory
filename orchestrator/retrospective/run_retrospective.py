import json
import os
import sys
import tempfile
from pathlib import Path

from shared import agent_output, config, outcomes
from shared.console import log
from try_fix import collect_events, factory_fix_request, file_failure, provider_alert, write_bug

from retrospective import (
    agent_run,
    event_verdicts,
    fix_budget,
    improvement_issues,
    judge_events,
    learning_pr,
    lesson_records,
    minor_findings,
    run_facts,
    story_report,
    tracker,
)
from retrospective.cause import name_cause


def lesson_main(number):
    repo = os.environ["GITHUB_REPOSITORY"]
    pat, token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    issue = json.loads(tracker.gh(["issue", "view", str(number), "--repo", repo, "--json", "title,body,comments,labels"], token).stdout)
    if not {tracker.LABEL, factory_fix_request.FACTORY_LABEL} & {l["name"] for l in issue.get("labels", [])}:
        log(f"#{number} is not a {tracker.LABEL} or {factory_fix_request.FACTORY_LABEL} issue; nothing to do")
        return 0
    work = Path(tempfile.mkdtemp(prefix="factory-run-"))
    facts_path, result_path = work / "lesson.json", work / "result.json"
    facts_path.write_text(json.dumps({"lesson_issue": number, "title": issue["title"], "body": issue["body"],
                                      "comments": [c["body"] for c in issue.get("comments", [])][-10:]}, indent=2))
    cfg, key = config.load(), os.environ.get("DEEPINFRA_API_KEY")
    if not key or "retrospective" not in cfg.get("roles", {}):
        return 0
    learning_pr.propose(config.FACTORY_DIR, cfg, repo, pat, token, key, facts_path, result_path, [number], os.environ.get("GITHUB_RUN_ID", "0"))
    return 0


def judge_run_events(events, result, cfg, key, repo, token, app, work, outcome):
    entries = event_verdicts.parse(result)
    open_warnings = [e for e in events if e["severity"] == "warning" and e["key"] not in entries]
    if open_warnings and key and "retrospective" in cfg.get("roles", {}):
        agent_key, budget = agent_run.mint_agent(cfg, key)
        if agent_key:
            entries.update(judge_events.answer(open_warnings, cfg, agent_key))
            agent_run.record_agent_spend(budget, agent_key, repo, token, os.environ.get("GITHUB_RUN_ID", "0"))
    try:
        fixed = fix_budget.warnings_fixed_today(repo, token, app)
    except Exception as e:  # noqa: BLE001 - counting never fails the run
        log(f"could not count today's fixed warnings, so no warning is fixed this run: {type(e).__name__}: {e}")
        fixed = event_verdicts.fix_cap(cfg.get("limits"))
    verdicts = event_verdicts.decide(events, entries, cfg.get("limits", {}), fixed)
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    (work / "artifacts" / "retrospective-verdicts.json").write_text(json.dumps(verdicts, indent=2))
    if verdicts:
        log("event verdicts:\n" + event_verdicts.render(verdicts))
    return verdicts


class Sightings:
    def __init__(self, repo, token, facts, promote_after):
        self.repo, self.token, self.facts, self.promote_after = repo, token, facts, promote_after
        self.seen_in = {}

    def count(self, number):
        try:
            return tracker.note_sighting(self.repo, self.token, number, self.facts, self.promote_after)
        except Exception as e:  # noqa: BLE001 - counting never fails the run
            log(f"could not count the sighting on #{number}, so it is not promoted this run: {type(e).__name__}: {e}")
            return 0

    def earned(self, number, severe=False):
        if number not in self.seen_in:
            self.seen_in[number] = self.count(number)
        return tracker.ready_for_fix(self.seen_in[number], self.promote_after, severe)


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

    def fresh_minors(self):
        minors = minor_findings.record_minors(self.repo, self.token, self.facts)
        return [n for n, proposed in minors if not proposed and self.sightings.earned(n)]

    def fresh_improvements(self):
        suggested, self.filed = improvement_issues.record_improvements(self.repo, self.token, self.facts)
        return [n for n, proposed in suggested if not proposed and self.sightings.earned(n)]

    def lesson_is_new(self, number, status, severe):
        if status == "reopened":
            return True
        return self.sightings.earned(number, severe) and (status == "new" or not tracker.already_proposed(self.repo, self.token, number))

    def fresh_lessons(self):
        recorded = [(lesson_records.record_lesson(self.repo, self.token, x, self.facts), x["severe"]) for x in self.lessons]
        return [n for (n, status), severe in recorded if n and self.lesson_is_new(n, status, severe)]

    def targets(self):
        outcome = self.d.get("outcome")
        stuck_issue = lesson_records.record_issue(self.repo, self.token, self.facts) if lesson_records.records_stuck_issue(outcome) else None
        self.sightings = Sightings(self.repo, self.token, self.facts, int(self.cfg.get("limits", {}).get("promote_after_runs", 2)))
        found = ([stuck_issue] if stuck_issue else []) + self.fresh_minors() + self.fresh_improvements() + self.fresh_lessons()
        return list(dict.fromkeys(found))

    def propose(self, targets):
        if not (targets and self.key and "retrospective" in self.cfg.get("roles", {})):
            return None
        failed = {"child": int(self.d["issue_number"]), "outcome": self.d.get("outcome"), "has_bugs": bool(self.facts.get("bugs"))} if self.stuck else None
        result_path = self.work / "retrospective-result.json"
        return learning_pr.propose(config.FACTORY_DIR, self.cfg, self.repo, self.pat, self.token, self.key, self.facts_path, result_path, targets, self.run_id, failed)

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
        result = self.propose(self.targets())
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
        if len(sys.argv) > 2 and sys.argv[1] == "lesson":
            sys.exit(lesson_main(int(sys.argv[2])))
        if len(sys.argv) > 3 and sys.argv[1] == "auto-merge-check":
            try:
                sys.exit(learning_pr.auto_merge_check(sys.argv[2], sys.argv[3]))
            except Exception as e:  # noqa: BLE001 - any doubt means a human merges it
                print(f"auto-merge check failed ({type(e).__name__}); a human merges this", flush=True)
                sys.exit(1)
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - the retrospective must never fail the run
        print(f"::warning::retrospective failed: {type(e).__name__}: {e}", flush=True)
        sys.exit(0)
