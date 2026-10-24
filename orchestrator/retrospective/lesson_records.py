import hashlib
import json
import re

from shared import outcomes
from try_fix import collect_events

from retrospective import run_facts, tracker

MAX_LESSONS = 3


EXTRA_ROUND_PASSES = 3


BUDGET_SHARE = 0.7


SLOW_STAGE_SECONDS = 900


def lesson_fingerprint(kind, basis):
    return hashlib.sha1(json.dumps([kind, basis]).encode()).hexdigest()[:8]


def lesson(kind, basis, detail, severe=False):
    return [{"kind": kind, "severe": severe, "detail": detail, "title": f"Lesson [{kind}] {lesson_fingerprint(kind, basis)}"}]


def audit_lessons(facts):
    if not facts.get("audit"):
        return []
    broken = "; ".join(f"{a['rule']}: {a['detail']}" for a in facts["audit"])
    return lesson("audit_violation", sorted(a["rule"] for a in facts["audit"]), "The run broke a design invariant: " + broken, severe=True)


def watchdog_lessons(facts):
    if facts["outcome"] != "watchdog_disabled":
        return []
    return lesson("watchdog_disabled", [], f"The watchdog switched a release off: {facts['message']}", severe=True)


def flag_lessons(facts):
    for note in (facts.get("flag_notes") or [])[:1]:
        named = "named" if note.get("guess", "").startswith("the flag") else "other"
        return lesson("flag_missing", [note.get("kind"), named],
                      f"A flag was missing at release ({note.get('kind')}): `{note.get('slug')}`. Likely cause: {note.get('guess')}.", severe=note.get("kind") != "missing_dark")
    return []


def many_rounds_lessons(facts):
    if facts["outcome"] not in outcomes.OK or facts.get("review_passes", 0) < EXTRA_ROUND_PASSES:
        return []
    blocking = sorted({s for r in facts["rounds"] for s in r["blocking"]})
    basis = facts["recurring_findings"] or sorted({tracker.normalize(s) for s in blocking})
    return lesson("many_rounds", basis, f"It needed {facts['review_passes']} review passes. Blocking findings across the rounds: " + "; ".join(blocking or ["none recorded"]))


def first_pass_lessons(facts):
    first_test = facts["rounds"][0]["tester_blocking"] if facts["rounds"] else []
    if facts["outcome"] not in outcomes.OK or not first_test:
        return []
    return lesson("first_pass_test_failure", sorted(tracker.normalize(s) for s in first_test), "The first test pass failed and the coder had to fix: " + "; ".join(first_test))


def budget_lessons(facts):
    if facts["outcome"] in outcomes.OK and facts.get("cap_usd") and (facts.get("spent_usd") or 0) >= BUDGET_SHARE * facts["cap_usd"]:
        return lesson("budget_high", [], f"It spent ${facts['spent_usd']:.2f} of its ${facts['cap_usd']:.2f} cap.")
    return []


def slow_stage_lessons(facts):
    slow = next((st for st in facts["stages"] if (st.get("seconds") or 0) > SLOW_STAGE_SECONDS), None)
    if not slow:
        return []
    return lesson("slow_stage", [slow["stage"]], f"The {slow['stage']} stage (round {slow['round']}) took {slow['seconds']:.0f}s.")


def lessons_from(facts):
    checks = (audit_lessons, watchdog_lessons, flag_lessons, many_rounds_lessons, first_pass_lessons, budget_lessons, slow_stage_lessons)
    found = [x for check in checks for x in check(facts)]
    found.sort(key=lambda x: not x["severe"])
    return found[:MAX_LESSONS]


def wants_fix_request(d, limits):
    return bool(limits.get("fix_requests", True)) and collect_events.run_failure(d)


def records_stuck_issue(outcome):
    return outcome not in outcomes.OK and outcome not in outcomes.ANSWERED + (outcomes.WATCHDOG_DISABLED, outcomes.PROVIDER_BLOCKED)


def record_issue(repo, token, facts):
    tracker.gh(["label", "create", tracker.LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    title = run_facts.title_for(facts)
    found = tracker.gh(["issue", "list", "--repo", repo, "--label", tracker.LABEL, "--state", "open", "--search", f"{run_facts.fingerprint(facts)} in:title",
                "--json", "number,title"], token).stdout
    for issue in json.loads(found or "[]"):
        if issue["title"] == title:
            tracker.gh(["issue", "comment", str(issue["number"]), "--repo", repo, "--body", "Happened again.\n\n" + run_facts.render_facts(facts)], token)
            return issue["number"]
    out = tracker.gh(["issue", "create", "--repo", repo, "--label", tracker.LABEL, "--title", title, "--body",
              run_facts.render_facts(facts) + "\n_A retrospective analysis follows._"], token).stdout
    m = re.search(r"/issues/(\d+)", out)
    return int(m.group(1)) if m else None


def record_lesson(repo, token, lesson, facts):
    tracker.gh(["label", "create", tracker.LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    tracker.gh(["label", "create", "fix-ineffective", "--repo", repo, "--color", "b60205", "--description", "A lesson came back after its fix merged"], token)
    found = tracker.gh(["issue", "list", "--repo", repo, "--label", tracker.LABEL, "--state", "all", "--search", f"{lesson['title']} in:title",
                "--json", "number,title,state"], token).stdout
    open_n, closed_n = tracker.pick_existing(json.loads(found or "[]"), lesson["title"])
    seen = f"{lesson['detail']}\n\nApp `{facts['app']}`, run: {facts['run_url']}"
    if open_n:
        tracker.gh(["issue", "comment", str(open_n), "--repo", repo, "--body", "Seen again.\n\n" + seen], token)
        return open_n, "again"
    if closed_n:
        tracker.gh(["issue", "reopen", str(closed_n), "--repo", repo], token)
        tracker.gh(["issue", "edit", str(closed_n), "--repo", repo, "--add-label", "fix-ineffective"], token)
        tracker.gh(["issue", "comment", str(closed_n), "--repo", repo, "--body",
            "**Fix ineffective:** this lesson was closed, and it happened again. The change that closed it did not stop it; "
            "consider undoing that change with a new one.\n\n" + seen], token)
        return closed_n, "reopened"
    out = tracker.gh(["issue", "create", "--repo", repo, "--label", tracker.LABEL, "--title", lesson["title"], "--body", seen], token).stdout
    m = re.search(r"/issues/(\d+)", out)
    return (int(m.group(1)) if m else None), "new"
