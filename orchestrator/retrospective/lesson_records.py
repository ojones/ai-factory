# Step 2 of the retrospective: one `factory-learning` issue per distinct failure or lesson (a fingerprint in the title collapses repeats into a
# comment). A lesson whose fix was merged and that comes back is reopened as `fix-ineffective`.
import hashlib
import json
import re

from shared import outcomes

from retrospective import run_facts, tracker

MAX_LESSONS = 3  # signals recorded per run, so one noisy run cannot flood the tracker


EXTRA_ROUND_PASSES = 3  # review passes at or above which a clean run is still a lesson (two fix rounds)


BUDGET_SHARE = 0.7


SLOW_STAGE_SECONDS = 900


def lesson_fingerprint(kind, basis):
    return hashlib.sha1(json.dumps([kind, basis]).encode()).hexdigest()[:8]


def lessons_from(facts):
    # Things a run taught the Factory beyond being stuck. Each is {kind, title, severe, detail}; at most
    # MAX_LESSONS, the severe ones first. A stuck run is recorded separately by record_issue.
    outcome, ok = facts["outcome"], facts["outcome"] in outcomes.OK
    found = []

    def add(kind, basis, detail, severe=False):
        found.append({"kind": kind, "severe": severe, "detail": detail,
                      "title": f"Lesson [{kind}] {lesson_fingerprint(kind, basis)}"})

    if facts.get("audit"):
        add("audit_violation", sorted(a["rule"] for a in facts["audit"]),
            "The run broke a design invariant: " + "; ".join(f"{a['rule']}: {a['detail']}" for a in facts["audit"]), severe=True)
    if outcome == "watchdog_disabled":
        add("watchdog_disabled", [], f"The watchdog switched a release off: {facts['message']}", severe=True)
    for note in (facts.get("flag_notes") or [])[:1]:
        # A flag was missing when it was needed (flag_lifecycle/missing_flag.py): record it and the guess, so a pattern can be fixed in the Orchestrator or the app.
        add("flag_missing", [note.get("kind"), "named" if note.get("guess", "").startswith("the flag") else "other"],
            f"A flag was missing at release ({note.get('kind')}): `{note.get('slug')}`. Likely cause: {note.get('guess')}.", severe=note.get("kind") != "missing_dark")
    if ok and facts.get("review_passes", 0) >= EXTRA_ROUND_PASSES:
        basis = facts["recurring_findings"] or sorted({tracker.normalize(s) for r in facts["rounds"] for s in r["blocking"]})
        add("many_rounds", basis, f"It needed {facts['review_passes']} review passes. Blocking findings across the rounds: "
            + "; ".join(sorted({s for r in facts["rounds"] for s in r["blocking"]}) or ["none recorded"]))
    first_test = facts["rounds"][0]["tester_blocking"] if facts["rounds"] else []
    if ok and first_test:
        add("first_pass_test_failure", sorted(tracker.normalize(s) for s in first_test),
            "The first test pass failed and the coder had to fix: " + "; ".join(first_test))
    if ok and facts.get("cap_usd") and (facts.get("spent_usd") or 0) >= BUDGET_SHARE * facts["cap_usd"]:
        add("budget_high", [], f"It spent ${facts['spent_usd']:.2f} of its ${facts['cap_usd']:.2f} cap.")
    for st in facts["stages"]:
        if (st.get("seconds") or 0) > SLOW_STAGE_SECONDS:
            add("slow_stage", [st["stage"]], f"The {st['stage']} stage (round {st['round']}) took {st['seconds']:.0f}s.")
            break
    found.sort(key=lambda x: not x["severe"])
    return found[:MAX_LESSONS]


def wants_fix_request(d, limits):
    # A fix request is filed for every Build Run that did not end well (`planned` and the good endings do not).
    return bool(limits.get("fix_requests", True)) and d.get("outcome") not in outcomes.OK and d.get("outcome") not in outcomes.ANSWERED + (outcomes.PROVIDER_BLOCKED,)


def records_stuck_issue(outcome):
    # Whether a run's ending gets the generic `Stuck run` lesson. A release the watchdog switched off is already a
    # specific, severe lesson (`watchdog_disabled`); recording it twice made two issues and two analyses for one event.
    return outcome not in outcomes.OK and outcome not in outcomes.ANSWERED + (outcomes.WATCHDOG_DISABLED, outcomes.PROVIDER_BLOCKED)


def record_issue(repo, token, facts):
    # Create the learning issue, or comment on the open one for the same fingerprint. Returns its number.
    tracker.gh(["label", "create", tracker.LABEL, "--repo", repo, "--color", "5319e7", "--description", "A stuck run to learn from"], token)
    title = run_facts.title_for(facts)
    found = tracker.gh(["issue", "list", "--repo", repo, "--label", tracker.LABEL, "--state", "open", "--search", f"{run_facts.fingerprint(facts)} in:title",
                "--json", "number,title"], token).stdout
    for issue in json.loads(found or "[]"):
        if issue["title"] == title:
            tracker.gh(["issue", "comment", str(issue["number"]), "--repo", repo, "--body", "Happened again.\n\n" + run_facts.render_facts(facts)], token)
            return issue["number"]
    out = tracker.gh(["issue", "create", "--repo", repo, "--label", tracker.LABEL, "--title", title, "--body",
              run_facts.render_facts(facts) + "\n_A retrospective analysis and, if one is possible, a proposed fix PR follow._"], token).stdout
    m = re.search(r"/issues/(\d+)", out)
    return int(m.group(1)) if m else None


def record_lesson(repo, token, lesson, facts):
    # Create or update the `factory-learning` issue for a lesson. Returns (number, status) with status
    # `new`, `again` (an open one exists) or `reopened` (a closed one came back: the fix did not work).
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
