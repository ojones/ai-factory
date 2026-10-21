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
        log(f"could not count today's fixed warnings: {type(e).__name__}: {e}")
        fixed = 0
    verdicts = event_verdicts.decide(events, entries, cfg.get("limits", {}), fixed)
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    (work / "artifacts" / "retrospective-verdicts.json").write_text(json.dumps(verdicts, indent=2))
    if verdicts:
        log("event verdicts:\n" + event_verdicts.render(verdicts))
    return verdicts


def main():
    work = Path(os.environ["BUILD_RUN_DIR"])
    d = agent_output.load_json(work / "state.json")
    if not d:
        return 0
    stuck = d.get("outcome") not in outcomes.OK
    repo = os.environ["GITHUB_REPOSITORY"]
    pat, token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    if d.get("outcome") in outcomes.ANSWERED:
        return 0
    facts = run_facts.collect_facts(work, d)
    if d.get("outcome") == "provider_blocked":
        try:
            log(f"provider alert: {provider_alert.file_provider_alert(repo, token, facts)}")
        except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
            log(f"could not file the provider alert: {type(e).__name__}: {e}")
        return 0
    cfg_limits = config.load().get("limits", {})
    lessons = lesson_records.lessons_from(facts)
    events = collect_events.from_run(facts, run_facts.fingerprint(facts))
    facts["events"] = events
    facts["signals"] = [{"kind": x["kind"], "detail": x["detail"]} for x in lessons]
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    facts_path, result_path = work / "artifacts" / "retrospective-facts.json", work / "retrospective-result.json"
    facts_path.write_text(json.dumps(facts, indent=2))
    stuck_issue = lesson_records.record_issue(repo, token, facts) if lesson_records.records_stuck_issue(d.get("outcome")) else None
    minors = minor_findings.record_minors(repo, token, facts)
    promote_after = int(cfg_limits.get("promote_after_runs", 2))
    seen_in = {}

    def earned(number, severe=False):
        if number not in seen_in:
            try:
                seen_in[number] = tracker.note_sighting(repo, token, number, facts, promote_after)
            except Exception as e:  # noqa: BLE001 - counting never fails the run
                log(f"could not count the sighting on #{number}: {type(e).__name__}: {e}")
                seen_in[number] = promote_after
        return tracker.ready_for_fix(seen_in[number], promote_after, severe)

    new_minors = [n for n, proposed in minors if not proposed and earned(n)]
    suggested, filed = improvement_issues.record_improvements(repo, token, facts)
    new_improvements = [n for n, proposed in suggested if not proposed and earned(n)]
    recorded = [(lesson_records.record_lesson(repo, token, x, facts), x["severe"]) for x in lessons]
    new_lessons = [n for (n, status), severe in recorded
                   if n and (status == "reopened" or (earned(n, severe) and (status == "new" or not tracker.already_proposed(repo, token, n))))]
    targets = list(dict.fromkeys(([stuck_issue] if stuck_issue else []) + new_minors + new_improvements + new_lessons))
    cfg, key = config.load(), os.environ.get("DEEPINFRA_API_KEY")
    result = None
    if targets and key and "retrospective" in cfg.get("roles", {}):
        failed = {"child": int(d["issue_number"]), "outcome": d.get("outcome"), "has_bugs": bool(facts.get("bugs"))} if stuck else None
        result = learning_pr.propose(config.FACTORY_DIR, cfg, repo, pat, token, key, facts_path, result_path, targets, os.environ.get("GITHUB_RUN_ID", "0"), failed)
    cause = name_cause(facts, result)
    verdicts = judge_run_events(events, result, cfg, key, repo, token, d["app"], work, d.get("outcome"))
    (work / "artifacts" / "retrospective-cause.json").write_text(json.dumps(cause, indent=2))
    filed_request, fixes = None, event_verdicts.fix_events(verdicts)
    if fixes and bool(cfg.get("limits", {}).get("fix_requests", True)):
        filed_events = file_failure.file_failures(repo, token, pat, fixes, facts, result, d.get("rollback"), cfg, key,
                                                  lambda budget, cred: write_bug.record_spend(budget, cred, repo, token, os.environ.get("GITHUB_RUN_ID", "0")))
        for got in filed_events:
            log(f"event {got['key']} handled ({got['target']}: {got['action']}) {got['url']}")
        filed_request = next((g for g in filed_events if g["severity"] == "failure"), None)
    bugs = []
    if facts.get("bugs") and stuck:
        try:
            carried = bool(filed_request and filed_request["action"] == "bug_intake")
            if story_report.note_bugs_on_story(repo, token, d["issue_number"], facts, carried):
                bugs = [{"kind": x["kind"], "check": x["check"], "url": ""} for x in facts["bugs"][:story_report.MAX_BUGS]]
        except Exception as e:  # noqa: BLE001
            log(f"could not note the bugs on the story: {type(e).__name__}: {e}")
    try:
        story_report.post_retrospective(repo, token, d["issue_number"], os.environ.get("GITHUB_RUN_ID", "0"),
                           story_report.render_retrospective(facts, filed, lessons, result, bugs, cause, verdicts))
    except Exception as e:  # noqa: BLE001
        log(f"could not post the retrospective on the issue: {type(e).__name__}: {e}")
    return 0


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
        print(f"retrospective failed: {type(e).__name__}: {e}", flush=True)
        sys.exit(0)
