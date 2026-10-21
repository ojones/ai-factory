from shared import outcomes

from retrospective import tracker

ROUTES = {"app": "a fix to the app's change, the failed change runs again once it is fixed", "factory": "a fix request for the Factory",
          "info": "left for a person"}
MAX_BUGS = 5


BUG_LABEL = "bug"


def bug_notes(facts):
    lines = ["## Bugs the tester saw", "", f"Run: {facts['run_url']}", ""]
    for x in facts["bugs"][:MAX_BUGS]:
        what = "behaviour that was live before this change stopped working" if x["kind"] == "regression" else f"a check of the new change failed (flag `{x['flag'] or 'none'}`)"
        lines += [f"- **{x['check']}** ({what})", f"  - Evidence: {x['evidence'] or 'none given'}"] + ([f"  - Repro: {x['repro']}"] if x.get("repro") else [])
    return "\n".join(lines) + "\n"


def note_bugs_on_story(repo, token, number, facts, carried):
    if not facts.get("bugs"):
        return False
    tracker.gh(["label", "create", BUG_LABEL, "--repo", repo, "--color", "d73a4a", "--description", "Something is not working"], token)
    tracker.gh(["issue", "edit", str(number), "--repo", repo, "--add-label", BUG_LABEL], token)
    if carried:
        return True
    marker = f"<!-- bugs:{facts['run_url']} -->"
    if marker in (tracker.gh(["issue", "view", str(number), "--repo", repo, "--json", "comments"], token).stdout or ""):
        return False
    tracker.gh(["issue", "comment", str(number), "--repo", repo, "--body", bug_notes(facts) + marker], token)
    return True


def render_retrospective(facts, filed, lessons, result=None, bugs=(), cause=None, verdicts=()):
    notes = []
    if facts.get("dark_broken"):
        notes.append("**Dark feature left behind**: its flag stays off and the next attempt fixes it forward.")
    if facts["outcome"] == "regression":
        notes.append("**Regression**: behaviour that was live before this change stopped working, so the live app was rolled back to the previous "
                     "version. The commits stay in `main`, behind a flag that is off, and are fixed forward.")
    for x in bugs:
        notes.append(f"Bug noted on this issue ({x['kind']}): {x['check']}")
    if facts["recurring_findings"]:
        notes.append("Findings that came back across rounds: " + "; ".join(facts["recurring_findings"][:3]))
    if facts["final_minor"]:
        notes.append(f"{len(facts['final_minor'])} minor finding(s) shipped open and were recorded.")
    for x in filed:
        notes.append(f"Improvement for the {'app' if x['target'] == 'managed_app' else 'Factory'}: {x['summary']}" + (f" ({x['url']})" if x["url"] else ""))
    for x in lessons:
        notes.append(f"Lesson: {x['detail'][:160]}")
    if result and result.get("root_cause"):
        notes.append(f"Cause named ({result.get('category')}): {result['root_cause'][:200]}")
    if cause and cause["category"] and facts["outcome"] not in outcomes.OK:
        notes.append(f"Cause: `{cause['category']}`, handled as: {ROUTES[cause['route']]}.")
    for v in verdicts:
        if v["event"]["severity"] == "warning" or v["verdict"] == "fix":
            notes.append(f"Event {v['verdict']} ({v['event']['severity']}): {v['event']['summary'][:100]}. {v['reason']}")
    if not notes:
        notes.append("Nothing to improve was found.")
    head = [f"## Retrospective: `{facts['outcome']}`", "", f"{facts['message'] or ''} ([run]({facts['run_url']}))", "",
            f"{facts['review_passes']} review pass(es), ${facts['spent_usd'] or 0:.2f} of a ${facts['cap_usd'] or 0:.2f} cap, "
            f"{len(facts['commits'])} commit(s) pushed.", ""]
    return "\n".join(head + [f"- {n}" for n in notes]) + "\n"


def post_retrospective(repo, token, number, run_id, body):
    marker = f"<!-- retrospective:{run_id} -->"
    seen = tracker.gh(["issue", "view", str(number), "--repo", repo, "--json", "comments"], token).stdout or ""
    if marker in seen:
        return False
    tracker.gh(["issue", "comment", str(number), "--repo", repo, "--body", body + "\n" + marker], token)
    return True
