"""A fix request: one GitHub issue for a Build Run that did not end well.

The run's own failure issue (in the Managed App repo) says that it failed. This is the issue that says what has to be fixed:
what happened, what the Orchestrator already did about it (the revert), an automated analysis, and numbered requirements
that can be checked afterwards. It is routed by the cause the post-mortem named:

  factory  a prompt, planner, Starter Template or orchestrator cause. An ai-factory issue labelled `factory-fix-request`.
           Adding `ready-for-factory-run` gives it to the Factory Run (the post-mortem Agent), which proposes a PR for a person
           to merge. The app planner is not used: it plans changes to Managed Apps, and this is a change to the Factory.
  app      the request itself was the problem (unclear, too big for the model). An *unstarted* Update Intake for the app,
           with the failure and the requirements written into the request. Adding `proceed-with-change` starts it: the
           planner plans it, then the usual coder, tester and reviewer run. It is unstarted so a person reads it first.
  info     no cause was named (or an infrastructure one). A `fix-request` issue in ai-factory for a person to read.

One open fix request per Intake and route: a run that fails again adds a comment instead of a second issue.
"""
import hashlib
import json
import re
import subprocess
import os

import update_intake

LABEL = "fix-request"
FACTORY_LABEL = "factory-fix-request"
FACTORY_CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap")
APP_CATEGORIES = ("spec_ambiguity", "model_limit")
MAX_ITEMS = 5


def inferred_category(category, outcome):
    """The cause to route by. A run that ran out of money or time was too big for its limits, which is the request's
    problem: that decides the route unless the post-mortem named a Factory cause that is not a prompt (an Agent that fails
    because its credential ran dry looks like a prompt gap, which it is not). With no cause named, the same rule applies."""
    if outcome in ("budget_exhausted", "time_limit") and category in (None, "", "prompt_gap", "infra", "unknown", "model_limit"):
        return "model_limit"
    return category or None


def route(category):
    """Where a fix request goes, from the cause the post-mortem named: factory, app or info."""
    if category in FACTORY_CATEGORIES:
        return "factory"
    if category in APP_CATEGORIES:
        return "app"
    return "info"


def fingerprint(app, origin, target, attempt=1):
    """One per app, original Intake, route and attempt, so a retry chain files a new issue per attempt but a repeat of the
    same attempt only comments."""
    return hashlib.sha1(f"{app}|{origin}|{target}|{attempt}".encode()).hexdigest()[:8]


def clip(text, n=300):
    return " ".join(str(text or "").split())[:n]


def revert_line(revert):
    """The revert, in one sentence for the issue."""
    if not revert:
        return "No revert was attempted."
    status = revert.get("status")
    if status == "reverted":
        deploy = revert.get("deploy", "not checked")
        return (f"`main` was put back to `{str(revert.get('restored', ''))[:8]}` (the state before this run) in commit "
                f"`{str(revert.get('sha', ''))[:8]}`; the deploy of that commit is **{deploy}**. The failed run's commits are still in the history.")
    if status == "failed":
        return f"**The automatic revert failed** ({clip(revert.get('reason'))}). `main` still has this run's commits, and any that were not behind a flag are live."
    return f"Nothing was reverted: {clip(revert.get('reason'), 200)}."


def raised_cap(outcome, cap, ceiling=10.0):
    """The cost cap for a retry. Money was the problem, so the retry gets twice as much, up to the Intake ceiling; any other
    ending keeps the cap it had. Returns None when there is nothing to change."""
    if outcome != "budget_exhausted" or not cap:
        return None
    new = min(float(ceiling), round(float(cap) * 2, 2))
    return new if new > float(cap) else None


def requirements(facts, result, revert, app_side=False):
    """Numbered, checkable requirements: what must be true once this is fixed. `app_side` is for a retry of the app's own
    request, which carries no requirements about fixing the Factory."""
    outcome, message = facts.get("outcome"), clip(facts.get("message"), 200)
    reqs = []
    status = (revert or {}).get("status")
    if status == "failed":
        reqs.append("`main` is back at the state before this run (the automatic revert failed and has to be done by hand), "
                    "and the app answers every route as it did before the run.")
    elif status == "reverted":
        reqs.append("Confirm the app behaves exactly as before the run (the revert restored `main`; check the routes this run touched).")
    elif facts.get("commits"):
        reqs.append("Check that `main` and the live app are in the state you want: this run pushed commits and they were not reverted "
                    f"({clip((revert or {}).get('reason'), 120) or 'no reason recorded'}).")
    recurring = facts.get("recurring_findings") or []
    blocking = [clip(s, 160) for s in facts.get("final_blocking") or []][:MAX_ITEMS]
    if outcome in ("round_limit", "stuck"):
        reqs.append("The same request ends in a clean pass within the configured review rounds" +
                    (f", without these blocking findings recurring: {'; '.join(blocking)}." if blocking else "."))
    elif outcome in ("budget_exhausted", "time_limit"):
        reqs.append(f"The same request finishes inside its cost cap and time limit (it stopped because: {message}), or is split into smaller requests that each do.")
    elif outcome == "crash":
        reqs.append(f"The run no longer crashes (it stopped with: {message}).")
    elif outcome == "watchdog_disabled":
        reqs.append(f"The regression the watchdog found is fixed ({message}). The flag it switched off is dead: remove it from flags.json together with the code it guarded, and deliver the corrected change behind a new flag of its own, which is released only after a clean pass.")
    else:
        reqs.append(f"Whatever stopped the run is resolved: {message}.")
    if recurring and outcome not in ("round_limit", "stuck"):
        reqs.append("These findings, which the coder did not resolve across rounds, stop recurring: " + "; ".join(clip(s, 100) for s in recurring[:MAX_ITEMS]) + ".")
    # The post-mortem Agent's own requirements are about how to fix the Factory. They belong in a Factory fix request and
    # not in a retry of the app's request (a retry that was told to build tester helpers would go and build them).
    for r in ((result or {}).get("requirements") or []) if not app_side else []:
        if isinstance(r, str) and r.strip() and clip(r, 300) not in reqs:
            reqs.append(clip(r, 300))
    reqs.append("A re-run of the same request ends `released` or `nothing_to_release` without anyone editing code by hand.")
    return reqs[:MAX_ITEMS + 3]


def should_autostart(target, attempt, lim):
    """Whether a fix request starts itself. Only the app route does (a Factory fix is a PR that a person merges), only when
    switched on, and only for the first `fix_request_max_attempts` automatic retries of one Intake: a retry that fails
    cannot file an endless chain of retries."""
    return target == "app" and bool(lim.get("fix_request_autostart", True)) and attempt <= int(lim.get("fix_request_max_attempts", 2))


def attempt_info(failing_body, failing_number):
    """(origin Intake, this attempt's number, earlier attempts' findings) for a failing Intake. A failing Intake that was
    itself an automatic retry carries its metadata; any other is the origin and the next attempt is the first."""
    meta = update_intake.fix_meta(failing_body)
    if meta:
        return meta.get("origin", failing_number), int(meta.get("attempt", 0)) + 1, [str(h) for h in meta.get("history", [])][-3:]
    return failing_number, 1, []


ORIGINAL_MARKER = "Original request:\n\n"
GUIDANCE = {
    "spec_ambiguity": ("Nobody is available to answer questions. Where the request is ambiguous or contradicts itself, choose the most conservative "
                       "reading (keep existing data and behaviour, remove nothing permanently, keep the change behind its flag) and state the "
                       "choice as an assumption."),
    "model_limit": "The last attempt was too much for one pass. Plan the smallest independently valuable change sets and keep each one small.",
}


def extract_original(text):
    """The request itself, from a request that may already be wrapped by an earlier fix request (so retries do not nest)."""
    return text.split(ORIGINAL_MARKER, 1)[1].strip() if ORIGINAL_MARKER in (text or "") else (text or "").strip()


def render(facts, result, revert, target, intake_url="", auto=None):
    """The issue body. `auto` is None, or {"attempt": n, "max": m, "started": bool} for an app-route fix request."""
    cat = (result or {}).get("category")
    lines = [f"## What happened", "",
             f"The Build Run for `{facts.get('app')}` ended **{facts.get('outcome')}**: {clip(facts.get('message'), 400)}", "",
             f"- Run: {facts.get('run_url')}", f"- Request: {intake_url or '#' + str(facts.get('issue_number'))}",
             f"- Review passes: {facts.get('review_passes', 0)}; spent ${(facts.get('spent_usd') or 0):.2f} of a ${(facts.get('cap_usd') or 0):.2f} cap"]
    for s in [clip(x, 200) for x in facts.get("final_blocking") or []][:MAX_ITEMS]:
        lines.append(f"- Still blocking at the end: {s}")
    lines += ["", "## What was done automatically", "", revert_line(revert), "", "## Analysis (automated, and may be wrong)", ""]
    if cat:
        lines.append(f"The post-mortem named the cause as **{cat}**: {clip((result or {}).get('root_cause'), 500)}")
        if (result or {}).get("change_summary") and result["change_summary"] != "none":
            lines.append(f"\nIt proposed: {clip(result['change_summary'], 400)}")
    else:
        lines.append("The post-mortem did not name a cause (it did not run or produced no usable analysis).")
    lines += ["", "## Requirements", ""] + [f"{i}. {r}" for i, r in enumerate(requirements(facts, result, revert), 1)]
    lines += ["", "## How this is picked up", ""]
    if target == "factory":
        lines.append(f"This is a fault in the Factory itself ({cat}). Add the label `ready-for-factory-run` and the Factory Run (the post-mortem Agent) will try a fix "
                     "and open a pull request for you to review. Nothing changes until you merge it.")
    elif target == "app" and auto and auto.get("started"):
        lines.append(f"This is about the request, not the Factory ({cat}). The Update Intake below was **started automatically** (automatic retry {auto['attempt']} "
                     f"of at most {auto['max']}); no review is needed. It goes through the planner and the usual coder, tester and reviewer. If it also fails, "
                     "the next retry is filed the same way; after the last one a person is asked. To stop it, cancel its Build Run and close this issue.")
    elif target == "app":
        why = (f"{auto['max']} automatic retries of this Intake have already failed, so a person is asked" if auto and auto.get("attempt", 1) > auto.get("max", 0)
               else "automatic retries are switched off")
        lines.append(f"This is about the request, not the Factory ({cat}). It was **not** started automatically ({why}). Read and edit the Update Intake below, "
                     "then add `proceed-with-change` to run it through the planner.")
    else:
        lines.append("No cause was named, or it was infrastructure. Read the run and decide; there is nothing to start automatically.")
    return "\n".join(lines) + "\n"


def app_request(facts, result, revert, original, category=None, history=(), cap_note=""):
    """The text of the Update Intake for the app route: what went wrong, what must be true this time, how to approach it,
    and the original request last (extracted, so a retry of a retry does not nest)."""
    reqs = requirements(facts, result, revert, app_side=True)
    parts = ["A previous attempt at the request below did not complete, so it is being asked again with what was learned.", "",
             f"What happened: it ended {facts.get('outcome')}: {clip(facts.get('message'), 300)} ({facts.get('run_url')})"]
    if facts.get("outcome") in ("budget_exhausted", "time_limit"):
        # Money or time ran out: say that, not the post-mortem's guess about which Agent happened to fail when it did.
        parts.append("Likely cause: the request was more than one pass could finish inside its limits.")
    elif category in APP_CATEGORIES:
        cause = clip((result or {}).get("root_cause"), 400)
        if cause:
            parts.append(f"Likely cause: {cause}")
    if cap_note:
        parts.append(cap_note)
    if history:
        parts += ["", "Earlier attempts:"] + [f"- {h}" for h in history]
    guide = GUIDANCE.get(category or "")
    if guide:
        parts += ["", "How to approach it this time: " + guide]
    parts += ["", "Requirements for this attempt:"] + [f"- {r}" for r in reqs]
    parts += ["", ORIGINAL_MARKER + (extract_original(original) or "(the original request could not be read; see the issue linked above)")]
    return "\n".join(parts)


def intake_form(app, request, cap=None):
    return (f"### App name\n\n{app}\n\n### What should change?\n\n{request}\n\n### Cost cap override (USD)\n\n{cap if cap else '_No response_'}\n")


# --- GitHub (not unit-tested) -------------------------------------------------


def gh(args, token):
    return subprocess.run(["gh", *args], capture_output=True, text=True, env={**os.environ, "GH_TOKEN": token})


def failing_issue(repo, number, token):
    """The body of the Intake whose run failed ('' if it cannot be read)."""
    p = gh(["issue", "view", str(number), "--repo", repo, "--json", "body"], token)
    try:
        return json.loads(p.stdout or "{}").get("body") or ""
    except ValueError:
        return ""


def provider_alert_body(facts):
    return (f"## The model provider has no balance\n\nA Build Run for `{facts.get('app')}` stopped because the model provider refused "
            f"the request: the account has no balance (HTTP 402, \"You need positive balance to do inference\").\n\n"
            f"- Run: {facts.get('run_url')}\n- Request: #{facts.get('issue_number')}\n\n"
            "## What was done automatically\n\n" + revert_line(facts.get("revert")) + "\n\n"
            "## What to do\n\n1. Add balance in the provider's dashboard (or turn on auto top-up).\n"
            "2. For an Update Intake that stopped, add `proceed-with-change` again (the Orchestrator removed it, so the label fires again). "
            "For a new app's Intake, add `ready-for-staging` again.\n\n"
            "Every Build Run fails until this is done. Nothing was retried automatically, and no fix request or post-mortem was started, "
            "because they would fail the same way.\n")


def file_provider_alert(repo, token, facts):
    """One open alert for the whole Factory: later blocked runs add a comment. Returns its URL."""
    for name, color, desc in (("provider-blocked", "b60205", "The model provider refuses requests (no balance)"),
                              ("needs-human", "b60205", "The Orchestrator stopped and needs a person")):
        update_intake.ensure_label(repo, name, token, color, desc)
    found = json.loads(gh(["issue", "list", "--repo", repo, "--label", "provider-blocked", "--state", "open", "--json", "number,url"], token).stdout or "[]")
    if found:
        gh(["issue", "comment", str(found[0]["number"]), "--repo", repo, "--body",
            f"**Blocked again**: `{facts.get('app')}`, request #{facts.get('issue_number')}, {facts.get('run_url')}"], token)
        return found[0]["url"]
    out = gh(["issue", "create", "--repo", repo, "--title", "Model provider has no balance: Build Runs are failing", "--label",
              "provider-blocked,needs-human", "--body", provider_alert_body(facts)], token)
    m = re.search(r"https://\S+/issues/\d+", out.stdout or "")
    return m.group(0) if m else ""


def file_fix_request(repo, token, pat, facts, result, revert, lim=None):
    """Create the fix request (or comment on the open one for this attempt) and, for the app route, start it. `token` is the
    Actions token; `pat` adds the start label (events made by the Actions token do not start workflows).
    Returns {target, url, started, attempt}."""
    lim = lim or {}
    category = inferred_category((result or {}).get("category"), facts.get("outcome"))
    result = dict(result or {}, category=category) if category else result
    target = route(category)
    app, number = facts.get("app"), facts.get("issue_number")
    body_text = failing_issue(repo, number, token)
    origin, attempt, history = attempt_info(body_text, number)
    fp = fingerprint(app, origin, target, attempt)
    for name, color, desc in ((LABEL, "d93f0b", "What has to be fixed after a Build Run ended badly"),
                              (FACTORY_LABEL, "5319e7", "A fix request for the Factory itself")):
        update_intake.ensure_label(repo, name, token, color, desc)
    found = json.loads(gh(["issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--search", f"{fp} in:title",
                           "--json", "number,title,url"], token).stdout or "[]")
    again = next((i for i in found if fp in i["title"]), None)
    if again:
        gh(["issue", "comment", str(again["number"]), "--repo", repo, "--body",
            f"**Failed again** ({facts.get('outcome')}): {clip(facts.get('message'), 300)}\n{facts.get('run_url')}\n\n{revert_line(revert)}"], token)
        return {"target": target, "url": again["url"], "started": False, "attempt": attempt}
    intake_url = f"https://github.com/{repo}/issues/{number}"
    started = False
    if target == "app":
        autostart = should_autostart(target, attempt, lim)
        auto = {"attempt": attempt, "max": int(lim.get("fix_request_max_attempts", 2)), "started": autostart}
        for name, color, desc in ((update_intake.FORM_LABEL, "1d76db", "A change request for an existing Managed App"), (f"app:{app}", "1d76db", ""),
                                  (update_intake.AUTO_FIX, "fbca04", "Filed and started by the Orchestrator after a Build Run failed"),
                                  ("needs-human", "b60205", "The Orchestrator stopped and needs a person"), (update_intake.GO, "0e8a16", "Start this change now")):
            update_intake.ensure_label(repo, name, token, color, desc)
        cap = update_intake.form_section(body_text, "Cost cap override (USD)")
        cap = None if cap in ("", "_No response_") else cap
        new_cap = raised_cap(facts.get("outcome"), facts.get("cap_usd"), lim.get("cost_cap_usd_ceiling", 10.0))
        cap_note = ""
        if new_cap:
            cap_note = f"The cost cap for this attempt is raised from ${float(facts.get('cap_usd')):.2f} to ${new_cap:.2f}, because the last attempt ran out of money."
            cap = f"{new_cap:.2f}"
        original = update_intake.form_section(body_text, "What should change?") or update_intake.form_section(body_text, "What should be built?")
        meta = {"origin": origin, "attempt": attempt, "history": history + [f"attempt {attempt - 1 or 'zero (the original request)'}: ended {facts.get('outcome')}: {clip(facts.get('message'), 160)}"]}
        request = app_request(facts, result, revert, original, category, meta["history"], cap_note)
        labels = f"{LABEL},{update_intake.FORM_LABEL},app:{app},{update_intake.AUTO_FIX}" + ("" if autostart else ",needs-human")
        body = (update_intake.with_fix_meta(meta) + "\n\n" + render(facts, result, revert, target, intake_url, auto) + "\n---\n\n" + intake_form(app, request, cap))
        out = gh(["issue", "create", "--repo", repo, "--title", f"{app}: fix request for #{origin} (attempt {attempt}) [{fp}]", "--label", labels,
                  "--body", body], token)
    else:
        labels = f"{LABEL},{FACTORY_LABEL}" if target == "factory" else LABEL
        out = gh(["issue", "create", "--repo", repo, "--title", f"Fix request [{fp}]: {category or 'unknown cause'} in {app}'s run for #{number}",
                  "--label", labels, "--body", render(facts, result, revert, target, intake_url)], token)
    m = re.search(r"https://\S+/issues/(\d+)", out.stdout or "")
    url, new_number = (m.group(0), m.group(1)) if m else ("", "")
    if target == "app" and new_number:
        if autostart:
            gh(["issue", "edit", new_number, "--repo", repo, "--add-label", update_intake.GO], pat)
            gh(["issue", "comment", new_number, "--repo", repo, "--body",
                f"Started automatically (automatic retry {attempt} of at most {auto['max']}). The planner runs first."], token)
            started = True
        else:
            gh(["issue", "comment", new_number, "--repo", repo, "--body",
                f"Not started: {auto['max']} automatic retries of #{origin} have already failed, or automatic retries are off. Read it, edit it if needed, "
                f"then add `{update_intake.GO}` to run it."], token)
        if str(number) != new_number:  # the failed Intake is superseded by its retry
            gh(["issue", "comment", str(number), "--repo", repo, "--body", f"Superseded by {url} ({'started automatically' if started else 'waiting for a person'})."], token)
            if update_intake.fix_meta(body_text) or started:
                gh(["issue", "close", str(number), "--repo", repo, "--reason", "not planned"], token)
    return {"target": target, "url": url, "started": started, "attempt": attempt}
