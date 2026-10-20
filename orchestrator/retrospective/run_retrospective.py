# After every Build Run, released or not: record what it taught, propose the fix as a PR, and report back on the story that started it (STEP 6.2).
# Runs as its own workflow step after `finalize`, on every run, and never fails the run. Facts, lesson issues, minor findings, improvements, the
# Retrospective Agent and its learning PR, the fix request and the story report each have their own file in this folder.
#
# Usage: python -m retrospective.run_retrospective [lesson <issue> | auto-merge-check <base> <head>]   (PYTHONPATH=orchestrator)
import json
import os
import sys
import tempfile
from pathlib import Path

from shared import agent_output, config, outcomes
from shared.console import log
from try_fix import fix_request

from retrospective import improvement_issues, learning_pr, lesson_records, minor_findings, run_facts, story_report, tracker
from retrospective.cause import name_cause


def lesson_main(number):
    # The Factory Run: analyse one existing lesson issue (label `ready-for-factory-run`) on demand.
    repo = os.environ["GITHUB_REPOSITORY"]
    pat, token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    issue = json.loads(tracker.gh(["issue", "view", str(number), "--repo", repo, "--json", "title,body,comments,labels"], token).stdout)
    if not {tracker.LABEL, fix_request.FACTORY_LABEL} & {l["name"] for l in issue.get("labels", [])}:
        log(f"#{number} is not a {tracker.LABEL} or {fix_request.FACTORY_LABEL} issue; nothing to do")
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


def main():
    work = Path(os.environ["BUILD_RUN_DIR"])
    d = agent_output.load_json(work / "state.json")
    if not d:
        return 0
    stuck = d.get("outcome") not in outcomes.OK
    repo = os.environ["GITHUB_REPOSITORY"]
    pat, token = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    if d.get("outcome") in outcomes.ANSWERED:
        return 0  # a refusal, or a wait for the owner's secrets, is an answer, not a failure, not a failure to learn from or retry
    facts = run_facts.collect_facts(work, d)
    if d.get("outcome") == "provider_blocked":
        # Not a lesson and not a fix request: nothing the Factory can change helps, and the Agent could not run anyway.
        try:
            log(f"provider alert: {fix_request.file_provider_alert(repo, token, facts)}")
        except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
            log(f"could not file the provider alert: {type(e).__name__}: {e}")
        return 0
    cfg_limits = config.load().get("limits", {})
    lessons = lesson_records.lessons_from(facts)
    facts["signals"] = [{"kind": x["kind"], "detail": x["detail"]} for x in lessons]
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    facts_path, result_path = work / "artifacts" / "retrospective-facts.json", work / "retrospective-result.json"
    facts_path.write_text(json.dumps(facts, indent=2))
    app_repo = f"{repo.split('/')[0]}/{d['app']}"
    stuck_issue = lesson_records.record_issue(repo, token, facts) if lesson_records.records_stuck_issue(d.get("outcome")) else None
    minors = minor_findings.record_minors(repo, token, app_repo, pat, facts)
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
    suggested, filed = improvement_issues.record_improvements(repo, token, app_repo, pat, facts)
    new_improvements = [n for n, proposed in suggested if not proposed and earned(n)]
    recorded = [(lesson_records.record_lesson(repo, token, x, facts), x["severe"]) for x in lessons]
    # The Agent looks at a lesson that came back after its fix, or has earned it (severe, or seen in enough distinct runs) and has no PR yet.
    new_lessons = [n for (n, status), severe in recorded
                   if n and (status == "reopened" or (earned(n, severe) and (status == "new" or not tracker.already_proposed(repo, token, n))))]
    targets = list(dict.fromkeys(([stuck_issue] if stuck_issue else []) + new_minors + new_improvements + new_lessons))
    cfg, key = config.load(), os.environ.get("DEEPINFRA_API_KEY")
    result = None
    if targets and key and "retrospective" in cfg.get("roles", {}):
        result = learning_pr.propose(config.FACTORY_DIR, cfg, repo, pat, token, key, facts_path, result_path, targets, os.environ.get("GITHUB_RUN_ID", "0"))
    cause = name_cause(facts, result)
    (work / "artifacts" / "retrospective-cause.json").write_text(json.dumps(cause, indent=2))
    filed_request = None
    if lesson_records.wants_fix_request(d, cfg.get("limits", {})):
        try:
            filed_request = fix_request.file_fix_request(repo, token, pat, facts, result, d.get("rollback"), cfg.get("limits", {}))
            log(f"fix request ({filed_request['target']}, {'started' if filed_request['started'] else 'not started'}): {filed_request['url']}")
        except Exception as e:  # noqa: BLE001 - the retrospective never fails the run
            log(f"could not file the fix request: {type(e).__name__}: {e}")
    bugs = []
    if facts.get("bugs") and stuck:
        try:  # app-side bugs go on the story's own issue; a retry on that issue (above) already carries them in its comment
            carried = bool(filed_request and filed_request["target"] == "app")
            if story_report.note_bugs_on_story(repo, token, d["issue_number"], facts, carried):
                bugs = [{"kind": x["kind"], "check": x["check"], "url": ""} for x in facts["bugs"][:story_report.MAX_BUGS]]
        except Exception as e:  # noqa: BLE001
            log(f"could not note the bugs on the story: {type(e).__name__}: {e}")
    try:  # the story keeps what the run found, whether or not it released
        story_report.post_retrospective(repo, token, d["issue_number"], os.environ.get("GITHUB_RUN_ID", "0"),
                           story_report.render_retrospective(facts, filed, lessons, result, bugs, cause))
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
