# Step 3: each improvement the reviewer or tester suggested for the Factory becomes a `factory-learning` issue in ai-factory, deduplicated and capped per run. One for
# the Managed App is a failure event (try_fix/collect_events.py) that the Retrospective judges; no suggestion issue is filed in the app's repo any more.
# The Agents only suggest; the Orchestrator files.
import hashlib
import re

from retrospective import minor_findings, tracker


def improvement_title(i):
    return f"Improvement [{hashlib.sha1((i['target'] + tracker.normalize(i['summary'])).encode()).hexdigest()[:8]}] {i['summary'][:60]}"


def record_improvements(repo, token, facts):
    # File what the reviewer and tester suggested for the Factory: a `factory-learning` issue in ai-factory (a comment when it is already open). A
    # `managed_app` improvement files nothing here and is only listed for the report. Capped per run.
    # Returns ([(factory issue number, already proposed)], [{target, summary, url}]) for the Agent and for the report.
    tracker.gh(["label", "create", tracker.LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    for_agent, filed = [], []
    for i in facts.get("improvements", [])[:minor_findings.MAX_MINORS]:
        detail = f"{i['summary']}\n\nEvidence: {i.get('evidence') or 'none given'}\n\nSuggested by the {i['source']} during the Build Run: {facts['run_url']}"
        if i["target"] == "managed_app":
            filed.append({"target": "managed_app", "summary": i["summary"], "url": ""})
            continue
        title = improvement_title(i)
        number = tracker.find_open_issue(repo, token, title, tracker.LABEL) or tracker.similar_open_issue(repo, token, i["summary"], tracker.LABEL)
        if number:
            tracker.gh(["issue", "comment", str(number), "--repo", repo, "--body",
                f"Suggested again in `{facts['app']}` by the {i['source']}: {i['summary']}\n\nEvidence: {i.get('evidence') or 'none given'}\n{facts['run_url']}"], token)
        else:
            out = tracker.gh(["issue", "create", "--repo", repo, "--label", tracker.LABEL, "--title", title, "--body", detail], token).stdout
            found = re.search(r"/issues/(\d+)", out)
            number = int(found.group(1)) if found else None
        if number:
            for_agent.append((number, tracker.already_proposed(repo, token, number)))
        filed.append({"target": "factory", "summary": i["summary"], "url": f"https://github.com/{repo}/issues/{number}" if number else ""})
    return for_agent, filed
