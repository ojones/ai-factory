# A fix request: one GitHub issue for a Build Run that did not end well.
#
# The run's own failure issue (in the Managed App repo) says that it failed. This is the issue that says what has to be fixed:
# what happened, what the Orchestrator already did about it (a deploy rollback, for a regression), an automated analysis, and numbered requirements
# that can be checked afterwards. It is routed by the cause the retrospective named:
#
#   factory  a prompt, planner, Starter Template or orchestrator cause. An ai-factory issue labelled `factory-fix-request`.
#            Adding `ready-for-factory-run` gives it to the Factory Run (the retrospective Agent), which proposes a PR for a person
#            to merge. The app planner is not used: it plans changes to Managed Apps, and this is a change to the Factory.
#   app      the request itself was the problem (unclear, too big for the model, or a release the watchdog switched off). The
#            story's OWN issue is updated, not a new one: a comment says it broke and why, and the retry state is hidden in it
#            (the attempt, the story's flag, what earlier attempts found, the guidance). While attempts remain the PAT puts
#            `proceed-with-change` back on the same issue, so the same story runs again with the same flag; after
#            `fix_request_max_attempts` it stays open, labelled `needs-human`, attached to its flag.
#   info     no cause was named (or an infrastructure one). A `fix-request` issue in ai-factory for a person to read.
#
# Factory and information routes: one open fix request per Intake and route; a run that fails again adds a comment instead of a second issue.
import hashlib
import json
import re

import update_intake
from shared import github

LABEL = "fix-request"
FACTORY_LABEL = "factory-fix-request"
FACTORY_CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap")
APP_CATEGORIES = ("spec_ambiguity", "model_limit", "regression")
MAX_ITEMS = 5


def inferred_category(category, outcome, has_bugs=False):
    # The cause to route by. A run that ran out of money or time was too big for its limits, which is the request's
    # problem: that decides the route unless the retrospective named a Factory cause that is not a prompt (an Agent that fails
    # because its credential ran dry looks like a prompt gap, which it is not). With no cause named, the same rule applies.
    if outcome in ("budget_exhausted", "time_limit") and category in (None, "", "prompt_gap", "infra", "unknown", "model_limit"):
        return "model_limit"
    if outcome in ("watchdog_disabled", "regression") and category not in FACTORY_CATEGORIES:
        return "regression"  # the change broke production: the story is retried, fixing the code behind the same flag
    if has_bugs and category not in FACTORY_CATEGORIES and category != "spec_ambiguity":
        return "regression"  # the tester saw checks fail: the story is retried on its own issue, with the bugs as notes
    return category or None


def route(category):
    # Where a fix request goes, from the cause the retrospective named: factory, app or info.
    if category in FACTORY_CATEGORIES:
        return "factory"
    if category in APP_CATEGORIES:
        return "app"
    return "info"


def fingerprint(app, origin, target, attempt=1):
    # One per app, original Intake, route and attempt, so a retry chain files a new issue per attempt but a repeat of the
    # same attempt only comments.
    return hashlib.sha1(f"{app}|{origin}|{target}|{attempt}".encode()).hexdigest()[:8]


def clip(text, n=300):
    return " ".join(str(text or "").split())[:n]


def rollback_line(rollback):
    # The rollback, in one sentence for the issue.
    if not rollback:
        return "No rollback was attempted."
    status = rollback.get("status")
    if status == "rolled_back":
        return (f"The live app was redeployed from `{str(rollback.get('restored', ''))[:8]}` (the version before this run) by the app's CI; "
                f"the deploy is **{rollback.get('deploy', 'not checked')}**. Nothing was reverted in git: this run's commits are still in `main`, behind a flag that is off.")
    if status == "failed":
        return (f"**The automatic rollback failed** ({clip(rollback.get('reason'))}). The live app may still be running the regressing version; "
                "redeploy the previous version by hand (run `rollback-fly.yml` for the commit before this run).")
    return f"Nothing was rolled back: {clip(rollback.get('reason'), 200)}."


def requirements(facts, result, rollback, app_side=False):
    # Numbered, checkable requirements: what must be true once this is fixed. `app_side` is for a retry of the app's own
    # request, which carries no requirements about fixing the Factory.
    outcome, message = facts.get("outcome"), clip(facts.get("message"), 200)
    reqs = []
    status = (rollback or {}).get("status")
    if status == "failed":
        reqs.append("The live app is back on the version before this run (the automatic rollback failed and has to be done by hand), "
                    "and it answers every route as it did before the run.")
    elif status == "rolled_back":
        reqs.append("Confirm the app behaves exactly as before the run (the previous version was redeployed; check the routes this run touched).")
    elif facts.get("commits") and outcome == "regression":
        reqs.append("Check that the live app is on the version you want: the tester found a regression and no rollback was done "
                    f"({clip((rollback or {}).get('reason'), 120) or 'no reason recorded'}).")
    for x in (facts.get("bugs") or [])[:MAX_ITEMS]:
        reqs.append(f"Fix this bug the tester saw ({'behaviour that was live before the change' if x.get('kind') == 'regression' else 'the new change, still dark'}): "
                    f"{clip(x.get('check'), 160)}. Evidence: {clip(x.get('evidence'), 200) or 'none given'}."
                    + (f" Repro: {clip(x.get('repro'), 160)}." if x.get("repro") else "") + " Add a test that fails without the fix.")
    recurring = facts.get("recurring_findings") or []
    blocking = [clip(s, 160) for s in facts.get("final_blocking") or []][:MAX_ITEMS]
    if outcome in ("round_limit", "stuck"):
        reqs.append("The same request ends in a clean pass within the configured review rounds" +
                    (f", without these blocking findings recurring: {'; '.join(blocking)}." if blocking else "."))
    elif outcome in ("budget_exhausted", "time_limit"):
        reqs.append(f"The same request finishes inside its cost cap and time limit (it stopped because: {message}), or is split into smaller requests that each do.")
    elif outcome == "crash":
        reqs.append(f"The run no longer crashes (it stopped with: {message}).")
    elif outcome == "regression":
        reqs.append(f"The regression is fixed ({message}): the behaviour the tester found broken works again with the change in place, behind the same flag, and a test covers it. The code is still in `main` (nothing was reverted), so fix it forward; the flag is released only after a clean pass.")
    elif outcome == "watchdog_disabled":
        reqs.append(f"The regression the watchdog found is fixed ({message}). The flag it switched off is dead: remove it from flags.json together with the code it guarded, and deliver the corrected change behind a new flag of its own, which is released only after a clean pass.")
    else:
        reqs.append(f"Whatever stopped the run is resolved: {message}.")
    if recurring and outcome not in ("round_limit", "stuck"):
        reqs.append("These findings, which the coder did not resolve across rounds, stop recurring: " + "; ".join(clip(s, 100) for s in recurring[:MAX_ITEMS]) + ".")
    # The retrospective Agent's own requirements are about how to fix the Factory. They belong in a Factory fix request and
    # not in a retry of the app's request (a retry that was told to build tester helpers would go and build them).
    for r in ((result or {}).get("requirements") or []) if not app_side else []:
        if isinstance(r, str) and r.strip() and clip(r, 300) not in reqs:
            reqs.append(clip(r, 300))
    reqs.append("A re-run of the same request ends `released` or `nothing_to_release` without anyone editing code by hand.")
    return reqs[:MAX_ITEMS + 3]


def should_autostart(target, attempt, lim):
    # Whether a fix request starts itself. Only the app route does (a Factory fix is a PR that a person merges), only when
    # switched on, and only for the first `fix_request_max_attempts` automatic retries of one Intake: a retry that fails
    # cannot file an endless chain of retries.
    return target == "app" and bool(lim.get("fix_request_autostart", True)) and attempt <= int(lim.get("fix_request_max_attempts", 2))


def attempt_info(failing_body, failing_number):
    # (origin Intake, this attempt's number, earlier attempts' findings) for a failing Intake. A failing Intake that was
    # itself an automatic retry carries its metadata; any other is the origin and the next attempt is the first.
    meta = update_intake.fix_meta(failing_body)
    if meta:
        return meta.get("origin", failing_number), int(meta.get("attempt", 0)) + 1, [str(h) for h in meta.get("history", [])][-3:]
    return failing_number, 1, []


RETRY_RE = re.compile(r"<!-- factory-retry:(.*?) -->", re.S)
RETRYING = "retrying"


def with_retry_state(state):
    # The hidden state of a story's retries, appended to the comment that reports a failure.
    return f"<!-- factory-retry:{json.dumps(state, separators=(',', ':')).replace('--', chr(92) + 'u002d' + chr(92) + 'u002d')} -->"


def retry_state(comments):
    # The newest retry state hidden in a list of comment bodies ({} when the story has never failed): the attempt number, the story's
    # flag(s), what earlier attempts found, the guidance for the next attempt and the failed run it answers.
    for body in reversed([c for c in comments if isinstance(c, str)]):
        m = RETRY_RE.search(body)
        if m:
            try:
                state = json.loads(m.group(1))
                return state if isinstance(state, dict) else {}
            except ValueError:
                continue
    return {}


def retry_note(flags, attempt=None):
    # What the reviewer and tester are told when a story is retried: its flag is released again once it passes.
    if not flags:
        return ""
    names = ", ".join(f"`{f}`" for f in flags)
    return (f"\n\nThis is retry {attempt or '?'} of a story that failed after its release; it keeps its flag {names}. Test it like a new flag: dark "
            "without the Preview Token (the feature must not be reachable) and working with the token, including the behaviour that broke "
            "the last time. When this change passes, the flag is released again.")


def retry_decision(state, facts, lim):
    # (duplicate, attempt, autostart) for a failure of a story whose retry state is `state`. A failure of a run already answered is a
    # duplicate; otherwise this is the next attempt, and it starts itself only while attempts remain.
    if state.get("last_run") and state.get("last_run") == facts.get("run_url"):
        return True, int(state.get("attempt", 0)), False
    attempt = int(state.get("attempt", 0)) + 1
    return False, attempt, should_autostart("app", attempt, lim)


ORIGINAL_MARKER = "Original request:\n\n"
GUIDANCE = {
    "spec_ambiguity": ("Nobody is available to answer questions. Where the request is ambiguous or contradicts itself, choose the most conservative "
                       "reading (keep existing data and behaviour, remove nothing permanently, keep the change behind its flag) and state the "
                       "choice as an assumption."),
    "model_limit": "The last attempt was too much for one pass. Plan the smallest independently valuable change sets and keep each one small.",
    "regression": ("The change broke something: the watchdog switched its flag off, or the tester saw checks fail (they are listed under the requirements). "
                   "Find what is wrong (the error lines or the failing checks, the diff and the tests), fix the code behind the same flag, and add a test that "
                   "fails without the fix. Do not remove the flag or the feature."),
}


def extract_original(text):
    # The request itself, from a request that may already be wrapped by an earlier fix request (so retries do not nest).
    return text.split(ORIGINAL_MARKER, 1)[1].strip() if ORIGINAL_MARKER in (text or "") else (text or "").strip()


def render(facts, result, rollback, target, intake_url="", auto=None, flags=()):
    # The issue body, or for the app route the comment on the story's own issue. `auto` is None, or {"attempt": n, "max": m, "started": bool}.
    cat = (result or {}).get("category")
    lines = ["## What happened", "",
             f"The Build Run for `{facts.get('app')}` ended **{facts.get('outcome')}**: {clip(facts.get('message'), 400)}", "",
             f"- Run: {facts.get('run_url')}", f"- Request: {intake_url or '#' + str(facts.get('issue_number'))}",
             f"- Review passes: {facts.get('review_passes', 0)}; spent ${(facts.get('spent_usd') or 0):.2f} of a ${(facts.get('cap_usd') or 0):.2f} cap"]
    if flags:
        lines.append("- Feature flag of this story: " + ", ".join(f"`{f}`" for f in flags) + " (kept through the retries)")
    for s in [clip(x, 200) for x in facts.get("final_blocking") or []][:MAX_ITEMS]:
        lines.append(f"- Still blocking at the end: {s}")
    lines += ["", "## What was done automatically", "", rollback_line(rollback), "", "## Analysis (automated, and may be wrong)", ""]
    if cat:
        lines.append(f"The retrospective named the cause as **{cat}**: {clip((result or {}).get('root_cause'), 500)}")
        if (result or {}).get("change_summary") and result["change_summary"] != "none":
            lines.append(f"\nIt proposed: {clip(result['change_summary'], 400)}")
    else:
        lines.append("The retrospective did not name a cause (it did not run or produced no usable analysis).")
    lines += ["", "## Requirements", ""] + [f"{i}. {r}" for i, r in enumerate(requirements(facts, result, rollback), 1)]
    lines += ["", "## How this is picked up", ""]
    if target == "factory":
        lines.append(f"This is a fault in the Factory itself ({cat}). Add the label `ready-for-factory-run` and the Factory Run (the retrospective Agent) will try a fix "
                     "and open a pull request for you to review. Nothing changes until you merge it.")
    elif target == "app" and auto and auto.get("started"):
        lines.append(f"This is about the request, not the Factory ({cat}). **This same issue is being retried automatically** (retry {auto['attempt']} of at most "
                     f"{auto['max']}), with the same feature flag; no review is needed. It goes through the planner and the usual coder, tester and reviewer. If it "
                     "fails again this issue is updated again; after the last retry a person is asked. To stop it, cancel its Build Run and remove `proceed-with-change`.")
    elif target == "app":
        why = (f"{auto['max']} automatic retries have already failed, so a person is asked" if auto and auto.get("attempt", 1) > auto.get("max", 0)
               else "automatic retries are switched off")
        lines.append(f"This is about the request, not the Factory ({cat}). It was **not** retried automatically ({why}); this issue stays here, attached to its flag. "
                     "Read the notes above, edit the issue if the request needs to change, then add `proceed-with-change` to retry.")
    else:
        lines.append("No cause was named, or it was infrastructure. Read the run and decide; there is nothing to start automatically.")
    return "\n".join(lines) + "\n"


def app_request(facts, result, rollback, original, category=None, history=(), cap_note="", flags=()):
    # The text of the Update App Intake for the app route: what went wrong, what must be true this time, how to approach it,
    # and the original request last (extracted, so a retry of a retry does not nest).
    reqs = requirements(facts, result, rollback, app_side=True)
    parts = [("A previous attempt at the request below did not complete, so it is being asked again with what was learned." if original is not None
              else "A previous attempt at this request did not complete, so it is being tried again with what was learned."), "",
             f"What happened: it ended {facts.get('outcome')}: {clip(facts.get('message'), 300)} ({facts.get('run_url')})"]
    if facts.get("outcome") in ("budget_exhausted", "time_limit"):
        # Money or time ran out: say that, not the retrospective's guess about which Agent happened to fail when it did.
        parts.append("Likely cause: the request was more than one pass could finish inside its limits.")
    elif category in APP_CATEGORIES:
        cause = clip((result or {}).get("root_cause"), 400)
        if cause:
            parts.append(f"Likely cause: {cause}")
    if cap_note:
        parts.append(cap_note)
    if history:
        parts += ["", "Earlier attempts:"] + [f"- {h}" for h in history]
    if flags:
        parts += ["", "This story keeps its feature flag through every retry: use exactly " + ", ".join(f"`{f}`" for f in flags) + " (do not invent another). "
                  "If it is already in `flags.json`, keep it and fix the code behind it; otherwise add it with exactly that slug."]
    guide = GUIDANCE.get(category or "")
    if guide:
        parts += ["", "How to approach it this time: " + guide]
    parts += ["", "Requirements for this attempt:"] + [f"- {r}" for r in reqs]
    if original is not None:
        parts += ["", ORIGINAL_MARKER + (extract_original(original) or "(the original request could not be read; see the issue linked above)")]
    return "\n".join(parts)


def intake_form(app, request, cap=None):
    return (f"### App name\n\n{app}\n\n### What should change?\n\n{request}\n\n### Cost cap override (USD)\n\n{cap if cap else '_No response_'}\n")


# --- GitHub (not unit-tested) -------------------------------------------------


def failing_issue(repo, number, token):
    # The body of the Intake whose run failed ('' if it cannot be read).
    p = github.run(["issue", "view", str(number), "--repo", repo, "--json", "body"], token)
    try:
        return json.loads(p.stdout or "{}").get("body") or ""
    except ValueError:
        return ""


def provider_alert_body(facts):
    return (f"## The model provider has no balance\n\nA Build Run for `{facts.get('app')}` stopped because the model provider refused "
            f"the request: the account has no balance (HTTP 402, \"You need positive balance to do inference\").\n\n"
            f"- Run: {facts.get('run_url')}\n- Request: #{facts.get('issue_number')}\n\n"
            "## What was done automatically\n\n" + rollback_line(facts.get("rollback")) + "\n\n"
            "## What to do\n\n1. Add balance in the provider's dashboard (or turn on auto top-up).\n"
            "2. For an Update App Intake that stopped, add `proceed-with-change` again (the Orchestrator removed it, so the label fires again). "
            "For a new app's Intake, add `ready-for-staging` again.\n\n"
            "Every Build Run fails until this is done. Nothing was retried automatically, and no fix request or retrospective was started, "
            "because they would fail the same way.\n")


def file_provider_alert(repo, token, facts):
    # One open alert for the whole Factory: later blocked runs add a comment. Returns its URL.
    for name, color, desc in (("provider-blocked", "b60205", "The model provider refuses requests (no balance)"),
                              ("needs-human", "b60205", "The Orchestrator stopped and needs a person")):
        github.ensure_label(repo, name, token, color, desc)
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--label", "provider-blocked", "--state", "open", "--json", "number,url"], token).stdout or "[]")
    if found:
        github.run(["issue", "comment", str(found[0]["number"]), "--repo", repo, "--body",
            f"**Blocked again**: `{facts.get('app')}`, request #{facts.get('issue_number')}, {facts.get('run_url')}"], token)
        return found[0]["url"]
    out = github.run(["issue", "create", "--repo", repo, "--title", "Model provider has no balance: Build Runs are failing", "--label",
              "provider-blocked,needs-human", "--body", provider_alert_body(facts)], token)
    m = re.search(r"https://\S+/issues/\d+", out.stdout or "")
    return m.group(0) if m else ""


def failing_story(repo, number, token):
    # The Intake whose run failed, as {"body", "comments": [bodies], "url"} (empty values if it cannot be read).
    p = github.run(["issue", "view", str(number), "--repo", repo, "--json", "body,comments,url"], token)
    try:
        doc = json.loads(p.stdout or "{}")
    except ValueError:
        doc = {}
    return {"body": doc.get("body") or "", "comments": [c.get("body", "") for c in doc.get("comments") or []], "url": doc.get("url") or ""}


def file_app_retry(repo, token, pat, facts, result, rollback, lim, category):
    # A failure of a story: the SAME issue is updated, never a new one. The failure, what was done about it and what to do next go in a
    # comment, with the retry state hidden in it (the attempt, the story's flag, what earlier attempts found, the guidance for the next
    # attempt). While attempts remain the PAT puts `proceed-with-change` back on the issue, so the same issue, with the same flag, runs
    # again; after `fix_request_max_attempts` it stays open, labelled `needs-human`, attached to its flag.
    # Returns {target, url, started, attempt}.
    number = facts.get("issue_number")
    story = failing_story(repo, number, token)
    state = retry_state(story["comments"])
    duplicate, attempt, autostart = retry_decision(state, facts, lim)
    if duplicate:
        return {"target": "app", "url": story["url"], "started": False, "attempt": attempt}
    history = [str(h) for h in state.get("history", [])][-3:]
    history.append(f"attempt {attempt - 1 or 'zero (the original request)'}: ended {facts.get('outcome')}: {clip(facts.get('message'), 160)}")
    flags = [f for f in (facts.get("flags") or state.get("flags") or []) if isinstance(f, str)]
    # A retry gets the cap the request had, never more: a story that could not finish inside it is too big for one pass, and the fix is to do less.
    cap_note = ("The last attempt ran out of money, and the cost cap is not raised for this one: do less in one pass, with the smallest change sets that work."
                if facts.get("outcome") == "budget_exhausted" else "")
    auto = {"attempt": attempt, "max": int(lim.get("fix_request_max_attempts", 2)), "started": autostart}
    new_state = {"attempt": attempt, "flags": flags, "history": history, "last_run": facts.get("run_url"),
                 "guidance": app_request(facts, result, rollback, None, category, history, cap_note, flags)[:6000]}
    for name, color, desc in ((RETRYING, "fbca04", "This story failed and is being retried on the same issue and flag"),
                              ("needs-human", "b60205", "The Orchestrator stopped and needs a person"), (update_intake.GO, "0e8a16", "Start this change now")):
        github.ensure_label(repo, name, token, color, desc)
    github.run(["issue", "comment", str(number), "--repo", repo, "--body", f"## Attempt {attempt - 1 or 'zero'} did not complete\n\n"
        + render(facts, result, rollback, "app", story["url"], auto, flags) + "\n" + with_retry_state(new_state)], token)
    if autostart:
        github.run(["issue", "edit", str(number), "--repo", repo, "--add-label", RETRYING, "--remove-label", "needs-human"], token)
        github.run(["issue", "edit", str(number), "--repo", repo, "--add-label", update_intake.GO], pat)  # the PAT: the Actions token would not start the workflow
    else:
        github.run(["issue", "edit", str(number), "--repo", repo, "--add-label", "needs-human", "--remove-label", RETRYING], token)
    return {"target": "app", "url": story["url"], "started": autostart, "attempt": attempt}


def file_fix_request(repo, token, pat, facts, result, rollback, lim=None):
    # For the Factory and information routes, create the fix request (or comment on the open one for this attempt). For the app route,
    # update the story's own issue and retry it (file_app_retry). `token` is the Actions token; `pat` adds the start label (events made by
    # the Actions token do not start workflows). Returns {target, url, started, attempt}.
    lim = lim or {}
    category = inferred_category((result or {}).get("category"), facts.get("outcome"), bool(facts.get("bugs")))
    result = dict(result or {}, category=category) if category else result
    target = route(category)
    if target == "app":
        return file_app_retry(repo, token, pat, facts, result, rollback, lim, category)
    app, number = facts.get("app"), facts.get("issue_number")
    body_text = failing_issue(repo, number, token)
    origin, attempt, history = attempt_info(body_text, number)
    fp = fingerprint(app, origin, target, attempt)
    for name, color, desc in ((LABEL, "d93f0b", "What has to be fixed after a Build Run ended badly"),
                              (FACTORY_LABEL, "5319e7", "A fix request for the Factory itself")):
        github.ensure_label(repo, name, token, color, desc)
    found = json.loads(github.run(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--search", f"{fp} in:title",
                           "--json", "number,title,url"], token).stdout or "[]")
    again = next((i for i in found if fp in i["title"]), None)
    if again:
        github.run(["issue", "comment", str(again["number"]), "--repo", repo, "--body",
            f"**Failed again** ({facts.get('outcome')}): {clip(facts.get('message'), 300)}\n{facts.get('run_url')}\n\n{rollback_line(rollback)}"], token)
        return {"target": target, "url": again["url"], "started": False, "attempt": attempt}
    intake_url = f"https://github.com/{repo}/issues/{number}"
    labels = f"{LABEL},{FACTORY_LABEL}" if target == "factory" else LABEL
    out = github.run(["issue", "create", "--repo", repo, "--title", f"Fix request [{fp}]: {category or 'unknown cause'} in {app}'s run for #{number}",
              "--label", labels, "--body", render(facts, result, rollback, target, intake_url)], token)
    m = re.search(r"https://\S+/issues/(\d+)", out.stdout or "")
    return {"target": target, "url": m.group(0) if m else "", "started": False, "attempt": attempt}
