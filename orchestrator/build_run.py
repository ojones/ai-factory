#!/usr/bin/env python3
"""Build Run orchestrator (ARCHITECTURE.md → Agents and Build Run stages).

Two subcommands, both run by .github/workflows/build-run.yml:

  run       coder → CI/deploy dark → reviewer + tester → fix loop → release
  finalize  always runs last: renders the Summary, Report and failure Issue
            from run/state.json, which `run` updates after every stage, so a
            crash, breach or killed job still reports.

Agents are OpenHands subprocesses with a whitelisted environment. They never
hold the PAT, the GrowthBook admin key, the Fly token or the DeepInfra parent
key; the coder only commits, and this process pushes.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import appstate
import audit
import planner
import update_intake
from update_intake import form_section  # noqa: F401 - the Issue Form parser lives with Update Intake

FACTORY_DIR = Path(__file__).resolve().parent.parent
DEEPINFRA = "https://api.deepinfra.com"
GROWTHBOOK_API = os.environ.get("GROWTHBOOK_API_HOST", "https://ai-factory-growthbook.fly.dev:3100") + "/api/v1"
PIPELINE = [("Test Gate", "test-gate.yml"), ("Build", "build.yml"), ("Deploy to Fly", "deploy-fly.yml")]
# Starter Template files the coder must not change: the workflows hold the Fly
# token, and the flag wrapper is the release gate's other half.
PROTECTED = (".github/", "fly.toml", "fly/", "backend/src/feature-flags.ts", "INTAKE.md")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
API_CHECK = str(FACTORY_DIR / "orchestrator" / "api_check.py")  # the helper the tester calls (see api_check.py)
# How a Build Run can end well. `planned`: an update Intake was split into child issues, each its own Build Run.
OK_OUTCOMES = ("released", "nothing_to_release", "planned")


class BudgetExhausted(Exception):
    pass


class ProviderBlocked(Exception):
    """The model provider refuses every request because the account has no balance (HTTP 402). Nothing a retry, a fix request
    or a post-mortem Agent does can help until someone tops it up, and each of them would fail the same way."""


class NeedsHuman(Exception):
    """kind: round_limit | time_limit | stuck | pipeline | other"""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


# --- pure logic (unit-tested) -------------------------------------------------


def parse_intake(body, default_cap, ceiling):
    # A new app's Intake asks "What should be built?"; an update Intake asks "What should change?".
    task = form_section(body, "What should be built?") or form_section(body, "What should change?")
    if not task or task == "_No response_":
        raise NeedsHuman("other", "The Intake's request field (\"What should be built?\" or \"What should change?\") is empty.")
    raw = form_section(body, "Cost cap override (USD)").lstrip("$")
    if not raw or raw == "_No response_":
        return task, float(default_cap)
    try:
        cap = float(raw)
    except ValueError:
        raise NeedsHuman("other", f"Cost cap override {raw!r} is not a number.")
    if not 0 < cap <= float(ceiling):
        raise NeedsHuman("other", f"Cost cap override ${cap} must be > 0 and <= the ${ceiling} ceiling.")
    return task, cap


def identify_intake(issue, app, number):
    """(is an Update Intake, its plan metadata) for the issue a Build Run was dispatched with, or NeedsHuman if the issue
    does not belong to `app`. A new app's Intake is titled with the app's name. An Update Intake has a free title,
    names the app in its form, and carries the `app:<slug>` label that Update Intake adds after checking the repo."""
    labels = {l["name"] for l in issue.get("labels", [])}
    body = issue.get("body") or ""
    if update_intake.FORM_LABEL not in labels:
        if issue["title"].strip() != app:
            raise NeedsHuman("other", f"Intake #{number} is titled {issue['title']!r}, not {app!r}.")
        return False, {}
    try:
        named = update_intake.app_name(body)
    except ValueError as e:
        raise NeedsHuman("other", f"Update Intake #{number}: {e}.")
    if named != app or f"app:{app}" not in labels:
        raise NeedsHuman("other", f"Update Intake #{number} names {named!r} and is labelled "
                                  f"{sorted(l for l in labels if l.startswith('app:'))}, not {app!r}.")
    return True, update_intake.plan_meta(body)


def derive_review(doc):
    """(clean, blocking, minor). The verdict comes from the findings, never the model's own field."""
    findings = doc.get("findings") if isinstance(doc, dict) else None
    if not isinstance(findings, list):
        raise ValueError("reviewer output has no findings list")
    # Whatever the reviewer marks blocking blocks, however much detail it gives.
    blocking = [f for f in findings if isinstance(f, dict) and f.get("severity") == "blocking"]
    minor = [f for f in findings if isinstance(f, dict) and f.get("severity") != "blocking"]
    return not blocking, blocking, minor


def finding_view(source, summary, evidence, raw):
    """A finding as handed to the coder: summary, evidence, and any of the detail fields present."""
    out = {"source": source, "summary": summary, "evidence": evidence}
    out.update({k: raw[k] for k in DETAIL_FIELDS if str(raw.get(k) or "").strip()})
    return out


def describe_finding(f):
    """One finding as an indented block for the coder's fix list."""
    where = f"{f['file']}:{f['line']}" if f.get("file") and f.get("line") else f.get("file") or ""
    rows = [("Where", where), ("Evidence", f.get("evidence")), ("Requirement", f.get("requirement")),
            ("Suggested fix", f.get("suggested_fix")), ("Repro", f.get("repro"))]
    body = "".join(f"\n    {k}: {v}" for k, v in rows if v)
    return f"- [{f['source']}] {f['summary']}{body}"


def previous_report(work, rnd):
    """The last round's tester report as a path, or a note that there is none (round 1)."""
    path = Path(work) / f"test-report-{rnd - 1}.json"
    return path if rnd > 1 and path.exists() else "none (this is the first test pass)"


CHECK_STATES = ("passed", "failed", "blocked", "not_run")


# Evidence that says, in the tester's own words, that it did not observe the thing it is reporting on. A model that writes
# this and still marks the check `passed` (seen in the first real run on an unobservable requirement) has not verified it.
UNOBSERVED_RE = re.compile(
    r"\b(unable to|not able to|cannot|can't|could not|couldn't|did not|didn't|no way to|no access to)\s+(directly\s+)?"
    r"(observe|verify|see|view|read|check|confirm|access|inspect|determine|validate)\b|\bunverifi(able|ed)\b|\bnot (been )?(verified|observed)\b", re.I)
RAN_A_TEST_RE = re.compile(r"\b(npm (run )?test|vitest|jest|unit test|test file|test suite|tests? (pass|passed|asserts?))\b", re.I)


def admits_unobserved(evidence):
    """True if the evidence says the thing was not observed, unless it also points at a test that was run for it."""
    text = str(evidence or "")
    return bool(UNOBSERVED_RE.search(text)) and not RAN_A_TEST_RE.search(text)


def check_state(r):
    """One tester result's state. `status` is one of CHECK_STATES; a report that only has the older
    boolean `passed` is read as passed or failed. Anything unrecognised counts as failed. A check marked `passed`
    whose own evidence admits it was not observed counts as `not_run`: it keeps the change from releasing."""
    if not isinstance(r, dict):
        return "failed"
    state = r["status"] if r.get("status") in CHECK_STATES else ("passed" if r.get("passed") is True else "failed")
    if state == "passed" and admits_unobserved(r.get("evidence")):
        return "not_run"
    return state


def load_api_results(path):
    """The api-check helper's own log (one JSON line per check it ran) as {id: result}; the last result for an id wins."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and isinstance(r.get("id"), str):
                    out[r["id"]] = r
    except OSError:
        pass
    return out


def _api_ids(result):
    ids = result.get("api")
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else ([ids] if isinstance(ids, str) else [])


def reconcile_api_checks(doc, api):
    """The tester's report with the helper's observations ranking above its judgement. A result that cites an api-check which
    failed cannot stay `passed`; one that cites a check the helper never ran cannot either; and a check the helper saw fail
    that no result mentions is added as a failure, so the tester cannot leave out what it was shown. Results that cite no
    api-check are untouched."""
    results = [dict(r) for r in (doc.get("results") if isinstance(doc, dict) else None) or [] if isinstance(r, dict)]
    cited = set()
    for r in results:
        ids = _api_ids(r)
        cited.update(ids)
        failing = [i for i in ids if i in api and not api[i].get("ok")]
        unknown = [i for i in ids if i not in api]
        if check_state(r) != "passed":
            continue
        if failing:
            r.update(status="failed", passed=False, evidence=(f"{r.get('evidence', '')} | the api-check helper observed otherwise: "
                     + "; ".join(f"{i}: {'; '.join(api[i].get('problems') or ['failed'])}" for i in failing)).strip(" |"))
        elif unknown:
            r.update(status="not_run", passed=False, evidence=(f"{r.get('evidence', '')} | cites api-check id(s) the helper never ran: "
                     + ", ".join(unknown)).strip(" |"))
    flag = next((r.get("flag") for r in results if r.get("flag")), "")
    for i, res in api.items():
        if not res.get("ok") and i not in cited:
            observed = res.get("observed") or {}
            results.append({"flag": flag, "check": f"api-check {i}: {res.get('name', i)}", "status": "failed", "passed": False, "api": [i],
                            "evidence": "the api-check helper observed a failure the report did not mention: "
                                        + "; ".join(res.get("problems") or ["failed"]) + f" (status {observed.get('status')})"})
    return {**doc, "results": results}


def derive_test(doc, expected_flags):
    """(passed, failures). passed is derived from the results, and every new flag needs a result.
    Only a check in the `passed` state passes: `failed`, `blocked` (something outside the app stopped
    the check) and `not_run` all keep the change from releasing. With no new flags (a first build)
    the results test the Intake's requirements, and there must be at least one."""
    results = doc.get("results") if isinstance(doc, dict) else None
    if not isinstance(results, list):
        raise ValueError("tester output has no results list")
    if not results and not expected_flags:
        raise ValueError("tester recorded no results")
    failures = [r for r in results if check_state(r) != "passed"]
    covered = {r.get("flag") for r in results if isinstance(r, dict)}
    for slug in expected_flags:
        if slug not in covered:
            failures.append({"flag": slug, "check": "coverage", "passed": False, "status": "not_run",
                             "evidence": "the tester recorded no result for this flag"})
    return not failures, failures


def verification_record(doc, expected_flags):
    """What was verified, as a compact record for the Report and Summary: a count per state, each
    check's state, and the limitations the tester reported (what it could not test or clean up)."""
    results = [r for r in (doc.get("results") if isinstance(doc, dict) else None) or [] if isinstance(r, dict)]
    counts = {state: 0 for state in CHECK_STATES}
    checks = []
    for r in results:
        state = check_state(r)
        counts[state] += 1
        checks.append({"flag": r.get("flag") or "", "check": r.get("check") or "", "status": state})
    covered = {r.get("flag") for r in results}
    for slug in expected_flags:
        if slug not in covered:
            counts["not_run"] += 1
            checks.append({"flag": slug, "check": "coverage", "status": "not_run"})
    limits = doc.get("limitations") if isinstance(doc, dict) else None
    limitations = [str(x) for x in limits if str(x).strip()] if isinstance(limits, list) else []
    return {"counts": counts, "checks": checks, "limitations": limitations}


def check_key(c):
    return f"{c['flag']}: {c['check']}" if c.get("flag") else c["check"]


def scoreboard_entry(rnd, sha, record, blocking):
    """One round of the run's scoreboard: every check's state at this commit and the blocking
    findings that were open. Written by the Orchestrator, never by an Agent."""
    return {"round": rnd, "sha": sha, "counts": record["counts"],
            "checks": {check_key(c): c["status"] for c in record["checks"]},
            "blocking": sorted({" ".join(str(b.get("summary", "")).lower().split()) for b in blocking})}


def open_items(entry):
    """What is still wrong in a round: the checks not passed plus the blocking findings."""
    return {f"check:{k}={v}" for k, v in entry["checks"].items() if v != "passed"} | {f"finding:{b}" for b in entry["blocking"]}


def stalled(entries, n):
    """True when the last `n` rounds each left exactly the same non-empty set of open items: the
    fix attempts in between changed nothing the checks can see. 0 or 1 disables it."""
    if n < 2 or len(entries) < n:
        return False
    last = [open_items(e) for e in entries[-n:]]
    return bool(last[0]) and all(x == last[0] for x in last)


ERROR_LOG_RE = re.compile(r'"level"\s*:\s*"(?:error|fatal)"', re.I)


def count_errors(log_text):
    """Error-level lines in a Managed App's structured (JSON) logs (STANDARDS-VISIBILITY.md)."""
    return len(ERROR_LOG_RE.findall(log_text or ""))


def watchdog_trip(samples, baseline_errors, max_failures, max_new_errors):
    """The reason to switch a just-released flag off, or None. `samples` are in time order, each
    {"healthy": bool, "errors": int}. Trips on `max_failures` health failures in a row, or on the
    error count rising `max_new_errors` above what the app logged before the release."""
    streak = 0
    for sample in samples:
        streak = 0 if sample["healthy"] else streak + 1
        if streak >= max_failures:
            return f"the health check failed {streak} times in a row after the release"
    if samples and max(sample["errors"] for sample in samples) - baseline_errors >= max_new_errors:
        return (f"error-level log lines rose from {baseline_errors} to {max(s['errors'] for s in samples)} "
                f"after the release (limit: {max_new_errors} new)")
    return None


def new_flag_slugs(base_json, head_json):
    def slugs(text):
        try:
            return [e["slug"] for e in json.loads(text) if isinstance(e, dict) and "slug" in e]
        except (ValueError, TypeError):
            return []
    base = set(slugs(base_json))
    return [s for s in slugs(head_json) if s not in base]


def protected_violations(changed_files):
    return [f for f in changed_files if f.startswith(PROTECTED) or f in PROTECTED]


LEDGER_LABEL = "factory-ledger"
LEDGER_RE = re.compile(r"^ledger (\d{4}-\d{2}-\d{2}) (\S+) (\d+(?:\.\d+)?) run:(\S+)\s*$")


def ledger_line(day, app, usd, run_id):
    """The comment a finished Build Run adds to the spend ledger issue."""
    return f"ledger {day} {app} {usd:.4f} run:{run_id}"


def ledger_total(comment_bodies, day):
    """USD recorded in the ledger for `day` (UTC date string). A line that is not a ledger line, or is for
    another day, counts for nothing; a run id seen twice counts once."""
    seen, total = set(), 0.0
    for body in comment_bodies:
        m = LEDGER_RE.match((body or "").strip())
        if m and m.group(1) == day and m.group(4) not in seen:
            seen.add(m.group(4))
            total += float(m.group(3))
    return round(total, 4)


def release_gate(ci_green, deploy_healthy, tester_passed, reviewer_clean, reviewed_sha, head_sha):
    """Release only when all four hold for the pushed SHA."""
    return all([ci_green, deploy_healthy, tester_passed, reviewer_clean]) and reviewed_sha == head_sha


def preview_token(master_secret, slug):
    """Same derivation as infra/app-staging/preview-token.sh."""
    return hmac.new(master_secret.encode(), slug.encode(), hashlib.sha256).hexdigest()


def summarize_token_usage(base_state):
    """Per-invocation context stats from OpenHands' persisted base_state.json.

    prompt_tokens of one LLM call is that call's context size, so the max over calls is the
    invocation's peak context. The condenser's own calls are counted separately.
    """
    metrics = (base_state.get("stats") or {}).get("usage_to_metrics") or {}
    agent = (metrics.get("agent") or {}).get("token_usages") or []
    condenser = (metrics.get("condenser") or {}).get("token_usages") or []
    prompts = [u.get("prompt_tokens", 0) for u in agent]
    latencies = (metrics.get("agent") or {}).get("response_latencies") or []
    return {"calls": len(agent), "condenser_calls": len(condenser),
            "peak_context": max(prompts, default=0), "last_context": prompts[-1] if prompts else 0,
            "prompt_tokens": sum(prompts), "completion_tokens": sum(u.get("completion_tokens", 0) for u in agent),
            "cache_read_tokens": sum(u.get("cache_read_tokens", 0) for u in agent),
            "llm_seconds": round(sum(l.get("latency", 0) for l in latencies), 1), "seconds": 0.0}


def merge_usage(a, b):
    """Combine two invocations' stats (a retry of the same role)."""
    if not a:
        return b
    if not b:
        return a
    out = {k: a[k] + b[k] for k in a if k not in ("peak_context", "last_context")}
    out["peak_context"] = max(a["peak_context"], b["peak_context"])
    out["last_context"] = b["last_context"]
    return out


def load_prompt(prompt_path):
    """A role prompt, with the shared reviewer rubric spliced in where it asks for `{{rubric}}`."""
    text = (FACTORY_DIR / "agents" / prompt_path).read_text()
    if "{{rubric}}" in text:
        text = text.replace("{{rubric}}", (FACTORY_DIR / "agents" / "prompts" / "reviewer-rubric.md").read_text().strip())
    return text


def render(template, values):
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    left = re.findall(r"\{\{\w+\}\}", out)
    if left:
        raise ValueError(f"unreplaced prompt placeholders: {left}")
    return out


# --- single-call review ------------------------------------------------------------

# The two files every route passes through: the reviewer must see them even when unchanged,
# to judge kill-switch ordering and how flags fail closed.
REVIEW_CONTEXT_FILES = ("backend/src/app.ts", "backend/src/feature-flags.ts")
SKIP_SUFFIXES = (".lock", "-lock.json", ".png", ".jpg", ".svg", ".ico", ".woff", ".woff2", ".map")

# Detail a finding may carry so the coder can act without exploring; all best-effort, "" when not applicable.
DETAIL_FIELDS = ("file", "line", "requirement", "suggested_fix", "repro")

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {"severity": {"type": "string", "enum": ["blocking", "minor"]},
                           "summary": {"type": "string"}, "evidence": {"type": "string"},
                           **{k: {"type": "string"} for k in DETAIL_FIELDS}},
            "required": ["severity", "summary", "evidence", *DETAIL_FIELDS], "additionalProperties": False}},
        "verdict": {"type": "string", "enum": ["clean", "changes_requested"]},
    },
    "required": ["analysis", "findings", "verdict"],
    "additionalProperties": False,
}


class ContextTooLarge(Exception):
    """The change does not fit in one prompt; the caller falls back to the exploring Agent."""


class FastReviewFailed(Exception):
    """The single call produced nothing usable; the caller falls back to the exploring Agent."""


def numbered(text):
    return "\n".join(f"{i}: {line}" for i, line in enumerate(text.split("\n"), 1))


def build_review_context(git, base, head, max_chars, spec=None):
    """Everything the reviewer would otherwise go and look up, in one message.

    `git(*args)` returns a git command's stdout ('' when it fails), run in the app checkout.
    Raises ContextTooLarge when the change cannot be shown whole, so a partial view never
    stands in for a review.
    """
    changed = [c for c in git("diff", "--name-only", "--diff-filter=d", base, head).split("\n") if c]
    shown = [c for c in changed if not c.endswith(SKIP_SUFFIXES)]
    extra = [f for f in REVIEW_CONTEXT_FILES if f not in shown]
    # The spec is the original INTAKE.md for a first build; for an update it is the change being made now
    # (INTAKE.md describes the app as first built, not this change).
    parts = [f"# Change request (the spec for this change)\n{spec}" if spec else f"# INTAKE.md\n{git('show', f'{head}:INTAKE.md')}",
             f"# flags.json\n{git('show', f'{head}:flags.json')}",
             f"# Diff {base[:8]}..{head[:8]}\n{git('diff', base, head, '--', ':(exclude)*lock*')}"]
    for path in shown + [f for f in extra if git("show", f"{head}:{f}")]:
        parts.append(f"# File at {head[:8]}: {path}\n{numbered(git('show', f'{head}:{path}'))}")
    slugs = re.findall(r'"slug"\s*:\s*"([^"]+)"', git("show", f"{head}:flags.json"))
    usage = []
    for slug in slugs:
        hits = git("grep", "-n", "-F", f'"{slug}"', head, "--", "backend", "frontend").strip()
        usage.append(f"- {slug}: " + (hits.replace(f"{head}:", "").replace("\n", "\n    ") if hits else "NOT USED ANYWHERE"))
    parts.append("# Where each declared flag is used (git grep)\n" + ("\n".join(usage) or "(no flags declared)"))
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        raise ContextTooLarge(f"{len(text):,} characters of context against a limit of {max_chars:,}")
    return text


def single_call_review(base_url, key, model, system, user, timeout=300, attempts=4):
    """One structured chat completion. Retries overload and server errors; returns (document, usage)."""
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "review_verdict", "schema": REVIEW_SCHEMA, "strict": True}}}
    last = None
    for attempt in range(1, attempts + 1):
        status, r = http("POST", f"{base_url}/chat/completions", key, body, timeout=timeout)
        if status == 200 and isinstance(r, dict):
            try:
                doc = json.loads(r["choices"][0]["message"]["content"])
                derive_review(doc)
                return doc, r.get("usage") or {}
            except (KeyError, IndexError, TypeError, ValueError) as e:
                last = f"unusable reply: {e}"
        else:
            last = f"HTTP {status}: {str(r)[:200]}"
            if status == 402:
                raise ProviderBlocked(BLOCKED_MESSAGE)
        if attempt < attempts and (status in (0, 429) or status >= 500 or status == 200):
            time.sleep(5 * attempt)
        else:
            break
    raise FastReviewFailed(last)


# --- plumbing -----------------------------------------------------------------


def log(msg):
    print(msg, flush=True)


def git_auth_env(header):
    """Environment variables that make git send `header` to GitHub. Passed this way, not as `git -c http.extraheader=...`, because a
    command line is readable by every user on the machine (`ps`, /proc/<pid>/cmdline) while an environment is not."""
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraheader", "GIT_CONFIG_VALUE_0": header}


def agent_command(cmd, env, user, pidfile=None):
    """`cmd` as it is run for an Agent. With a `user` (limits.agent_isolation: user) it runs as that unprivileged account through
    sudo: the variables in `env` are passed by name, so no value shows on a command line, and a wrapper records the process group
    in `pidfile` so the runner (which cannot signal another user's processes) can kill it through sudo."""
    if not user:
        return cmd
    names = ",".join(k for k in env if k != "PATH")
    wrapper = []
    if pidfile:
        wrapper = ["bash", "-c", 'ps -o pgid= -p $$ | tr -d " " > "$0"; exec "$@"', str(pidfile)]
    return ["sudo", "-n", "-u", user, f"--preserve-env={names}", "env", f"PATH={env.get('PATH', '')}", *wrapper, *cmd]


def kill_agent(proc, user, pidfile):
    """Kill an Agent's whole process group, whether it runs as the runner or, through sudo, as the Agent user."""
    import signal
    if user and pidfile:
        try:
            pgid = Path(pidfile).read_text().strip()
            if pgid.isdigit():
                subprocess.run(["sudo", "-n", "kill", "-KILL", "--", f"-{pgid}"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def isolation_problems(outputs):
    """What an isolation self-check found wrong, from {probe: output of the probe run as the Agent user}. Empty means isolated."""
    problems = []
    if outputs.get("whoami", "").strip() in ("", os.environ.get("USER", "runner"), "runner"):
        problems.append("the Agent user is not a different account from the Orchestrator's")
    if "SELF-CHECK-SECRET" in outputs.get("environ", ""):
        problems.append("an Agent can read the Orchestrator's environment through /proc")
    if outputs.get("workspace", "").strip():
        problems.append("an Agent can list the runner's workspace")
    if outputs.get("env_names", "").strip():
        problems.append("the Agent's environment holds credential variables: " + outputs["env_names"].strip().replace("\n", ", "))
    if outputs.get("sudo", "").strip() == "yes":
        problems.append("the Agent user can use sudo")
    return problems


def silent_too_long(last_progress, now, stall_seconds):
    """True when an Agent's output has not grown for `stall_seconds` (0 turns the check off)."""
    return stall_seconds > 0 and now - last_progress >= stall_seconds


def run_watched(cmd, cwd, env, out_path, timeout_s, stall_s, poll=5.0, user=None, pidfile=None):
    """Run an Agent writing its event stream to `out_path`. Returns its exit status, or "timeout" after `timeout_s` of wall time,
    or "stall" when the stream stops growing for `stall_s` seconds (the process group is killed either way). A real run once sat
    45 minutes twice with no output at all, so a silent Agent is cut off long before the overall timeout."""
    with open(out_path, "w") as f:
        proc = subprocess.Popen(agent_command(cmd, env, user, pidfile), cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True)
        began = last_change = time.time()
        size = -1
        while True:
            try:
                return proc.wait(timeout=poll)
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            current = os.path.getsize(out_path)
            if current != size:
                size, last_change = current, now
            reason = "timeout" if now - began >= timeout_s else "stall" if silent_too_long(last_change, now, stall_s) else None
            if reason:
                kill_agent(proc, user, pidfile)
                proc.wait()
                return reason


def sh(cmd, cwd=None, env=None, check=True, timeout=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}... failed ({p.returncode}): {(p.stderr or p.stdout)[-600:]}")
    return p


def http(method, url, token=None, body=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, (json.loads(raw) if raw else {})
            except ValueError:
                return r.status, raw[:500].decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500].decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


def json_problem(path, check=None):
    """Why an Agent's output file cannot be used, in words the Agent can act on; None when it can. Used to tell the
    Agent on its second attempt what was wrong with its first."""
    try:
        text = Path(path).read_text()
    except OSError:
        return f"the file {path} was not written"
    if not text.strip():
        return f"the file {path} is empty"
    try:
        doc = json.loads(text)
    except ValueError as e:
        where = f" at line {e.lineno} column {e.colno}" if hasattr(e, "lineno") else ""
        return (f"it is not valid JSON ({getattr(e, 'msg', e)}{where}); the usual cause is a quote, newline or backslash "
                "inside a string that was not escaped")
    try:
        if check is not None and check(doc) is False:
            return "its contents were not accepted"
    except (ValueError, AttributeError, TypeError) as e:
        return f"its contents were not accepted: {e}"
    return None


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def load_config():
    import yaml
    return yaml.safe_load((FACTORY_DIR / "agents" / "profiles.yml").read_text())


class Budget:
    """The run's one cap, enforced and metered by DeepInfra scoped JWTs.

    A spending-limited JWT can carry only one model, so each Agent invocation gets its own
    single-model JWT limited to what is left of the run's cap. DeepInfra refuses the first call
    after a JWT's limit (403) and the crossing call completes. The run's spend is the sum of every
    JWT's spending_current, so there are still no per-Agent budgets.
    """

    def __init__(self, admin_key, cap, ttl):
        self.admin_key, self.cap, self.ttl = admin_key, cap, ttl
        self.tokens = {}  # jwt -> last read spending_current

    def mint(self, model, share=1.0):
        """`share` < 1 splits what is left between invocations that run at the same time, so
        together they cannot spend past the cap."""
        remaining = round((self.cap - self.spent_known()) * share, 6)
        if remaining <= 0:
            raise BudgetExhausted(f"${self.spent_known():.4f} spent against a ${self.cap:.2f} cap")
        status, r = http("POST", f"{DEEPINFRA}/v1/scoped-jwt", self.admin_key,
                         {"api_key_name": "auto", "models": [model], "expires_delta": self.ttl, "spending_limit": remaining})
        if status == 402:
            raise ProviderBlocked(BLOCKED_MESSAGE)
        if status != 200 or "token" not in r:
            raise RuntimeError(f"could not mint scoped JWT: HTTP {status} {r}")
        print(f"::add-mask::{r['token']}", flush=True)
        self.tokens[r["token"]] = 0.0
        return r["token"]

    def spent_known(self):
        return sum(self.tokens.values())

    def refresh(self, jwt):
        status, r = http("GET", f"{DEEPINFRA}/v1/scoped-jwt?jwtoken={jwt}", self.admin_key)
        if status != 200:
            raise RuntimeError(f"could not read JWT spend: HTTP {status}")
        self.tokens[jwt] = float(r["spending_current"])
        return self.spent_known()


class State:
    def __init__(self, path, app, issue, run_url):
        self.path = Path(path)
        self.d = {"app": app, "issue_number": issue, "run_url": run_url, "outcome": "running", "message": "",
                  "cap_usd": None, "spent_usd": 0.0, "base_sha": None, "head_sha": None, "review_passes": 0,
                  "commits": [], "stages": [], "release": None, "blocking": [], "verification": None, "scoreboard": [],
                  "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=2))
        tmp.replace(self.path)

    def stage(self, name, agent, rnd, cost, verdict, usage=None):
        self.d["stages"].append({"stage": name, "agent": agent, "round": rnd,
                                 "cost_usd": round(cost, 6), "verdict": verdict, "usage": usage})
        self.save()
        return self.d["stages"][-1]


# --- the Build Run ------------------------------------------------------------


class BuildRun:
    agent_user = None  # set in __init__ from AGENT_USER; a class default so a bare test instance runs Agents as the same account
    def __init__(self):
        e = os.environ
        self.app = e["APP_NAME"]
        self.issue = e["ISSUE_NUMBER"]
        if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", self.app) or len(self.app) > 30 or not self.issue.isdigit():
            raise SystemExit(f"invalid inputs: app_name={self.app!r} issue_number={self.issue!r}")
        self.factory_repo = e["GITHUB_REPOSITORY"]
        self.owner = self.factory_repo.split("/")[0]
        self.app_repo = f"{self.owner}/{self.app}"
        self.run_id = e.get("GITHUB_RUN_ID", "0")
        self.run_url = f"{e.get('GITHUB_SERVER_URL', 'https://github.com')}/{self.factory_repo}/actions/runs/{self.run_id}"
        self.pat = e["FACTORY_PAT"]
        self.factory_token = e["FACTORY_GH_TOKEN"]
        self.work = Path(e["BUILD_RUN_DIR"])
        self.app_dir = Path(e["APP_DIR"])
        self.art = self.work / "artifacts"
        self.art.mkdir(parents=True, exist_ok=True)
        self.cfg = load_config()
        self.lim = self.cfg["limits"]
        self.state = State(self.work / "state.json", self.app, self.issue, self.run_url)
        self.start = time.time()
        self.deadline = self.start + self.lim["time_limit_minutes"] * 60
        self.cap = None
        self.meter = None
        self._usage = None
        # limits.agent_isolation: user -> the workflow created this unprivileged account and put the work directories where only it
        # and the runner can reach them; every Agent then runs as it.
        self.agent_user = e.get("AGENT_USER") or None
        self.lock = threading.Lock()  # guards the meter, the state and log output across parallel Agents
        self.preview = None
        self.build_kind = "first build"  # becomes "update" in setup() when the base commit has history
        self.auth_header = "Authorization: Basic " + base64.b64encode(
            f"x-access-token:{self.pat}".encode()).decode()
        print(f"::add-mask::{self.auth_header.split()[-1]}", flush=True)

    # --- gh / git

    def gh(self, args, token=None, check=True):
        return sh(["gh", *args], env={**os.environ, "GH_TOKEN": token or self.pat}, check=check)

    def git(self, *args, check=True, cwd=None):
        return sh(["git", *args], cwd=cwd or self.app_dir, check=check)

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()

    # --- limits

    def check_limits(self):
        if self.meter and self.cap is not None and self.state.d["spent_usd"] >= self.cap:
            raise BudgetExhausted(f"${self.state.d['spent_usd']:.4f} spent against a ${self.cap:.2f} cap")
        if time.time() > self.deadline:
            raise NeedsHuman("time_limit", f"the {self.lim['time_limit_minutes']}-minute time limit was reached")

    def record_spend(self, jwt):
        with self.lock:
            self.state.d["spent_usd"] = round(self.meter.refresh(jwt), 6)
            self.state.save()
            return self.state.d["spent_usd"]

    # --- setup

    def setup(self):
        out = self.gh(["issue", "view", self.issue, "--repo", self.factory_repo, "--json", "title,body,labels"],
                      token=self.factory_token).stdout
        issue = json.loads(out)
        self.update_intake, self.plan_meta = identify_intake(issue, self.app, self.issue)
        self.fix_meta = update_intake.fix_meta(issue["body"] or "")
        if self.fix_meta:
            self.state.d["fix"] = self.fix_meta
        self.state.d["intake_kind"] = "update" if self.update_intake else "new"
        self.task, self.cap = parse_intake(issue["body"] or "", self.lim["cost_cap_usd_default"],
                                           self.lim["cost_cap_usd_ceiling"])
        self.spec = self.task  # what the reviewer and tester check the work against; the planner may narrow it
        # The cap the issue asked for, if it asked for one, so child issues of a plan keep it instead of the default.
        raw_cap = form_section(issue["body"] or "", "Cost cap override (USD)").lstrip("$")
        self.cap_override = raw_cap if raw_cap and raw_cap != "_No response_" else None
        self.state.d["cap_usd"] = self.cap
        self.state.d["context_goal_tokens"] = self.lim.get("context_goal_tokens", 100000)
        self.state.save()
        self.check_daily_cap()
        self.prepare_agent_user()
        provider_check(self.cfg["provider"]["base_url"], os.environ["DEEPINFRA_API_KEY"], self.cfg["roles"]["coder"]["model"])
        self.wait_for_capacity()
        self.meter = Budget(os.environ["DEEPINFRA_API_KEY"], self.cap, self.lim["jwt_ttl_seconds"])
        self.preview = preview_token(os.environ["PREVIEW_MASTER_SECRET"], self.app)
        print(f"::add-mask::{self.preview}", flush=True)
        # Clone with the PAT passed per command only, so the checkout stores no credential
        # and the coder (who runs in it) cannot push or read one.
        sh(["git", "clone", "-q", f"https://github.com/{self.app_repo}.git", str(self.app_dir)],
           env={**os.environ, **git_auth_env(self.auth_header)})
        self.share_with_agent(self.app_dir)
        self.install_dependencies()
        self.git("config", "user.name", "ai-factory-coder")
        self.git("config", "user.email", "coder@ai-factory.local")
        self.state.d["base_sha"] = self.head()
        # The base of a first build is the seed commit, the repository's root. Any later Build Run
        # starts from a commit with history, so its change is an update that needs flags.
        has_parent = bool(self.git("rev-list", "--parents", "-n", "1", "HEAD").stdout.split()[1:])
        self.build_kind = "update" if has_parent else "first build"
        self.state.d["build_kind"] = self.build_kind
        self.state.save()
        log(f"Intake #{self.issue}: app {self.app}, cap ${self.cap:.2f}, base {self.state.d['base_sha'][:8]}")

    def prepare_agent_user(self):
        """With isolation on: put the helper the tester calls where the Agent user can read it, and prove isolation holds before
        any Agent runs. A run that cannot prove it stops, because an Agent next to the Orchestrator's secrets is what this prevents."""
        if not self.agent_user:
            return
        tools = self.work / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copy(API_CHECK, tools / "api_check.py")
        self.api_check_path = str(tools / "api_check.py")
        problems = self.isolation_self_check()
        self.state.d["isolation"] = {"user": self.agent_user, "problems": problems}
        self.state.save()
        if problems:
            raise NeedsHuman("other", "Agent isolation is on but not effective: " + "; ".join(problems))
        log(f"Agent isolation: Agents run as {self.agent_user}; self-check passed")

    def isolation_self_check(self):
        """Run probes as the Agent user (no model involved) and return what is wrong; see isolation_problems."""
        marker = subprocess.Popen(["sleep", "60"], env={**os.environ, "ISOLATION_MARK": "SELF-CHECK-SECRET"}, start_new_session=True)
        try:
            env = {"PATH": os.environ.get("PATH", "")}
            workspace = os.environ.get("GITHUB_WORKSPACE", "/home/runner/work")
            probes = {"whoami": "id -un", "environ": f"cat /proc/{marker.pid}/environ 2>/dev/null | tr '\\0' '\\n'",
                      "workspace": f"ls '{workspace}' 2>/dev/null",
                      "env_names": "env | cut -d= -f1 | grep -E '^(FACTORY_|FLY_API|GROWTHBOOK|DEEPINFRA|PREVIEW_MASTER|GITHUB_TOKEN|GH_TOKEN|ACTIONS_RUNTIME_TOKEN|ACTIONS_ID_TOKEN|ACTIONS_CACHE_URL|ACTIONS_RESULTS_URL)' || true",
                      "sudo": "sudo -n true 2>/dev/null && echo yes || echo no"}
            outputs = {}
            for name, script in probes.items():
                p = subprocess.run(agent_command(["bash", "-c", script], env, self.agent_user), env=env, capture_output=True, text=True, timeout=60)
                outputs[name] = p.stdout
            return isolation_problems(outputs)
        except (OSError, subprocess.TimeoutExpired) as e:
            return [f"the self-check could not run: {type(e).__name__}: {e}"]
        finally:
            marker.kill()

    def share_with_agent(self, path):
        """Make `path` readable and writable by both the Agent user and this process (what was just cloned or installed was created
        by one of them). No-op without isolation."""
        if self.agent_user:
            sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{self.agent_user}:rwX,u:{os.environ.get('USER', 'runner')}:rwX", str(path)], check=False)

    def install_dependencies(self):
        """Install once, here, so the coder starts with node_modules instead of spending agent turns on it.
        Later rounds reuse the checkout, and restore_tree/clean leave ignored node_modules alone. Runs with
        the coder's minimal environment, so the dependencies' install scripts never see the runner's secrets.
        A failure is only logged: the coder can still install for itself."""
        if not (self.app_dir / "package-lock.json").exists():
            return
        began = time.time()
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR", "CI") if k in os.environ}
        try:
            code = sh(agent_command(["npm", "ci", "--no-audit", "--no-fund"], env, self.agent_user), cwd=self.app_dir, env=env,
                      check=False, timeout=900).returncode
            self.share_with_agent(self.app_dir)
        except (subprocess.TimeoutExpired, OSError):
            code = "timeout"
        log(f"npm ci {'ok' if code == 0 else f'failed ({code}); the coder will install for itself'} in {time.time() - began:.0f}s")

    def ledger_issue(self):
        """The number of the open spend-ledger issue in ai-factory, or None before the first run has made one."""
        out = self.gh(["issue", "list", "--repo", self.factory_repo, "--label", LEDGER_LABEL, "--state", "open",
                       "--json", "number"], token=self.factory_token, check=False).stdout
        found = json.loads(out or "[]")
        return found[0]["number"] if found else None

    def check_daily_cap(self):
        """Refuse to start a Build Run once today's finished runs have spent `daily_cost_cap_usd`. Runs still
        in flight are not counted until they finish, so concurrent runs can overshoot by their own caps."""
        cap = float(self.lim.get("daily_cost_cap_usd", 0) or 0)
        if cap <= 0:
            return
        number = self.ledger_issue()
        if not number:
            return
        day = time.strftime("%Y-%m-%d", time.gmtime())
        out = self.gh(["api", f"repos/{self.factory_repo}/issues/{number}/comments?per_page=100&since={day}T00:00:00Z",
                       "--paginate", "--jq", ".[].body"], token=self.factory_token, check=False).stdout
        total = ledger_total(out.split("\n"), day)
        self.state.d["daily_spent_usd"] = total
        if total >= cap:
            raise NeedsHuman("other", f"today's Build Runs have already spent ${total:.2f} of the ${cap:.2f} daily cap; "
                                      "try again tomorrow or raise `limits.daily_cost_cap_usd`")

    def wait_for_capacity(self):
        cap = self.lim["max_simultaneous_build_runs"]
        give_up = time.time() + 30 * 60
        while True:
            out = self.gh(["run", "list", "--repo", self.factory_repo, "--workflow", "build-run.yml",
                           "--status", "in_progress", "--json", "databaseId"], token=self.factory_token).stdout
            others = [r for r in json.loads(out) if str(r["databaseId"]) != self.run_id]
            if len(others) < cap:
                return
            if time.time() > give_up:
                raise NeedsHuman("other", f"{len(others)} other Build Run(s) in flight (cap {cap}) for 30 minutes")
            log(f"{len(others)} other Build Run(s) in flight (cap {cap}); waiting")
            time.sleep(60)

    # --- agents

    def model_for(self, role, label):
        """The role's model. The coder may name a stronger `fix_model` for every attempt after round 1."""
        profile = self.cfg["roles"][role]
        if role == "coder" and str(label) != "1" and profile.get("fix_model"):
            return profile["fix_model"]
        return profile["model"]

    def agent_env(self, role, jwt, extra=None, home=None, model=None):
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR", "CI") if k in os.environ}
        if home:
            env["HOME"] = str(home)
        profile = self.cfg["roles"][role]
        env.update({"LLM_MODEL": "openai/" + (model or profile["model"]), "LLM_BASE_URL": self.cfg["provider"]["base_url"],
                    "LLM_API_KEY": jwt, "RUNTIME": "process"})
        env.update(extra or {})
        return env

    def invoke(self, role, label, values, extra_env=None, cwd=None, home=None, share=1.0, note=None):
        """One headless OpenHands invocation. Safe to call from several threads at once when each
        has its own `home` (OpenHands keeps its conversations there) and `cwd`.
        Returns (exit status, 'timeout' if killed; cost; token usage)."""
        self.check_limits()
        model = self.model_for(role, label)
        prompt = render(load_prompt(self.cfg["roles"][role]["prompt"]), {"app_name": self.app, "build_kind": self.build_kind,
                                                                         "spec": getattr(self, "spec", None) or getattr(self, "task", ""), **values})
        if note:
            prompt += (f"\n\nYour previous attempt was rejected: {note}. Do the work again as needed and write the file again. "
                       "Build the JSON with a short Python script and json.dump, not by typing it by hand.")
        with self.lock:
            before = self.state.d["spent_usd"]
            jwt = self.meter.mint(model, share)
        if self.agent_user and not home:
            home = self.work / "home-agent"  # the runner's own home is closed to the Agent user
        if home:
            Path(home).mkdir(parents=True, exist_ok=True)
        jsonl = self.art / f"openhands-{role}-{label}.jsonl"
        known = self.conversation_dirs(home)
        began = time.time()
        rc = run_watched(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd or self.app_dir,
                         self.agent_env(role, jwt, extra_env, home, model), jsonl, self.lim["agent_timeout_minutes"] * 60,
                         float(self.lim.get("agent_stall_minutes", 0)) * 60, user=self.agent_user,
                         pidfile=self.work / f"pgid-{role}-{label}.txt")
        if rc == "stall":
            with self.lock:
                log(f"{role} ({label}): no output for {self.lim.get('agent_stall_minutes')} minutes; killed it so the attempt can restart")
        after = self.record_spend(jwt)
        blocked = scan_for_provider_block(jsonl)
        if blocked:  # the account ran dry (possibly mid-run): stop everything, do not count it as the Agent's failure
            with self.lock:
                log(f"{role} ({label}): {blocked}")
            raise ProviderBlocked(blocked)
        usage = self.collect_usage(role, label, known, home)
        if usage:
            usage["seconds"] = round(time.time() - began, 1)  # wall time; minus llm_seconds is tool and wait time
        # Spend is read from the shared total, so with two Agents running its delta would include
        # the other's; the JWT's own spend is this invocation's exact cost.
        cost = self.meter.tokens[jwt]
        lines = [f"::group::{role} ({label})",
                 f"{role} ({label}) exited {rc}; cost ${cost:.4f}; run total ${after:.4f} of ${self.cap:.2f}", "::endgroup::"]
        if usage:
            goal = self.lim.get("context_goal_tokens", 100000)
            lines.insert(2, f"{role} ({label}) context: {usage['calls']} calls, peak {usage['peak_context']:,} tokens; "
                         f"{usage['seconds']:.0f}s wall, {usage['llm_seconds']:.0f}s in the model"
                         + (f" (over the {goal:,} goal)" if usage["peak_context"] > goal else ""))
        with self.lock:  # one block, so parallel Agents' groups do not interleave
            for line in lines:
                log(line)
        return rc, cost, usage

    def run_agent(self, role, label, values, extra_env=None):
        """The sequential form: records cost and usage on the Build Run for the caller to read."""
        rc, self._last_cost, usage = self.invoke(role, label, values, extra_env)
        self._usage = merge_usage(self._usage, usage)
        return rc

    def conversations_root(self, home=None):
        return Path(home or os.environ.get("HOME", "~")).expanduser() / ".openhands" / "conversations"

    def conversation_dirs(self, home=None):
        root = self.conversations_root(home)
        return {p.name for p in root.iterdir()} if root.is_dir() else set()

    def collect_usage(self, role, label, known, home=None):
        """Read the conversation this invocation created and keep its raw state as an artifact."""
        root = self.conversations_root(home)
        for name in sorted(self.conversation_dirs(home) - known):
            src = root / name / "base_state.json"
            doc = load_json(src)
            if doc is not None:
                (self.art / f"openhands-{role}-{label}-state.json").write_text(src.read_text())
                return summarize_token_usage(doc)
        return None

    def take_usage(self):
        usage, self._usage = self._usage, None
        return usage

    def agent_json(self, role, label, values, path, extra_env=None, check=None, cwd=None, home=None, share=1.0):
        """Run a role that writes a JSON file; one retry if the file is missing or malformed.
        Returns (document, cost, token usage)."""
        total_cost, usage, note = 0.0, None, None
        for attempt in (1, 2):
            Path(path).unlink(missing_ok=True)
            _, cost, used = self.invoke(role, f"{label}{'' if attempt == 1 else 'b'}", values, extra_env, cwd, home, share, note=note)
            total_cost += cost
            usage = merge_usage(usage, used)
            doc = load_json(path)
            try:
                if doc is not None and (check is None or check(doc) is not False):
                    return doc, total_cost, usage
            except (ValueError, AttributeError, TypeError):
                pass
            note = json_problem(path, check)  # read before the next attempt removes the file
            self.restore_tree(cwd)
        raise NeedsHuman("other", f"the {role} produced no valid output file twice" + (f" (last problem: {note})" if note else ""))

    def restore_tree(self, cwd=None):
        """Read-only roles must leave the tree untouched; undo it if they did not."""
        if self.git("status", "--porcelain", cwd=cwd).stdout.strip():
            log("A read-only Agent modified the working tree; restoring it.")
            self.git("reset", "-q", "--hard", "HEAD", cwd=cwd)
            self.git("clean", "-fdq", cwd=cwd)

    # --- coder + push

    def coder(self, label, task, findings_path):
        task0, attempts = task, 0
        base = self.head()
        while True:
            self.run_agent("coder", label, {"round": label, "task": task, "findings_path": findings_path})
            cost, head = self._last_cost, self.head()
            problem = None
            if head == base:
                problem = "You made no commit. Make the change, then run `git add` and `git commit`."
            elif self.git("merge-base", "--is-ancestor", base, head, check=False).returncode != 0:
                self.git("reset", "-q", "--hard", base)
                problem = "You rewrote history. Add new commits on top of the existing ones only."
            else:
                changed = self.git("diff", "--name-only", f"{base}..{head}").stdout.split("\n")
                bad = protected_violations([c for c in changed if c])
                if bad:
                    self.git("reset", "-q", "--hard", base)
                    problem = f"Your commits changed protected Starter Template files ({', '.join(bad)}). They were discarded. Redo the work without touching them."
            if problem:
                attempts += 1
                self.state.stage("Coder", "coder", label, cost, f"rejected: {problem[:60]}", self.take_usage())
                if attempts >= 3:
                    raise NeedsHuman("other", f"the coder could not produce an acceptable commit: {problem}")
                task = f"{problem}\n\nOriginal task:\n{task0}"
                continue
            self.check_limits()
            sh(["git", "push", "-q", "origin", "HEAD:main"], cwd=self.app_dir, env={**os.environ, **git_auth_env(self.auth_header)})
            self.state.d["head_sha"] = head
            self.state.d["commits"].append(head)
            self.state.stage("Coder", "coder", label, cost, f"pushed {head[:8]}", self.take_usage())
            return head

    # --- CI / deploy

    def wait_run(self, workflow, sha):
        give_up = time.time() + self.lim["pipeline_timeout_minutes"] * 60
        while time.time() < give_up:
            self.check_limits()
            out = self.gh(["run", "list", "--repo", self.app_repo, "--workflow", workflow, "--limit", "30",
                           "--json", "databaseId,headSha,status,conclusion,url"]).stdout
            runs = sorted((r for r in json.loads(out) if r["headSha"] == sha), key=lambda r: r["databaseId"])
            # Test Gate and Build finish at different times and each starts a Deploy run; the first one
            # finds the other not done and skips its deploy job. That run says "success" but deployed
            # nothing, so it is not the run to wait for.
            runs = [r for r in runs if not (workflow == "deploy-fly.yml" and r["status"] == "completed"
                                            and self.deploy_skipped(r["databaseId"]))]
            if runs and runs[-1]["status"] == "completed":
                return runs[-1]
            time.sleep(10)
        raise NeedsHuman("pipeline", f"{workflow} did not finish for {sha[:8]} within {self.lim['pipeline_timeout_minutes']} minutes")

    def deploy_skipped(self, run_id):
        out = self.gh(["run", "view", str(run_id), "--repo", self.app_repo, "--json", "jobs"], check=False).stdout
        try:
            jobs = json.loads(out).get("jobs", [])
        except ValueError:
            return False
        return any(j.get("name") == "deploy" and j.get("conclusion") == "skipped" for j in jobs)

    def healthy(self):
        for _ in range(12):
            status, body = http("GET", f"https://{self.app}.fly.dev/api/health", timeout=20)
            if status == 200:
                return True
            time.sleep(5)
        return False

    def failure_context(self, failed, sha, n):
        ctx = self.work / f"context-{n}"
        ctx.mkdir(parents=True, exist_ok=True)
        name, run = failed
        if run:
            p = self.gh(["run", "view", str(run["databaseId"]), "--repo", self.app_repo, "--log-failed"], check=False)
            (ctx / "failed-run.log").write_text((p.stdout or p.stderr)[-30000:])
        fly_env = {**os.environ, "FLY_API_TOKEN": os.environ.get("FLY_API_TOKEN", "")}
        for fname, args in (("fly-status.txt", ["status"]), ("fly-logs.txt", ["logs", "--no-tail"])):
            try:
                p = sh(["flyctl", *args, "--app", self.app], env=fly_env, check=False, timeout=120)
                text = p.stdout or p.stderr
            except (OSError, subprocess.TimeoutExpired) as e:
                text = f"flyctl unavailable: {e}"
            (ctx / fname).write_text(text[-15000:])
        return ctx

    def pipeline(self, sha):
        """Wait for Test Gate → Build → Deploy on sha, handling failures; returns the final green SHA."""
        retries, fixes, n = self.lim["pipeline_retries"], 0, 0
        while True:
            failed = None
            for name, wf in PIPELINE:
                run = self.wait_run(wf, sha)
                if run["conclusion"] != "success":
                    failed = (name, run)
                    break
            if failed is None and not self.healthy():
                failed = ("Health check", None)
            if failed is None:
                self.state.stage("CI / Build / Deploy", "-", "-", 0, f"green, deployed {sha[:8]}")
                return sha
            n += 1
            ctx = self.failure_context(failed, sha, n)
            url = failed[1]["url"] if failed[1] else f"https://github.com/{self.app_repo}/actions"
            diag, cost, usage = self.agent_json(
                "pipeline", f"p{n}", {"head_sha": sha, "failure_run_url": url, "context_dir": ctx,
                                      "diagnosis_path": self.work / f"diagnosis-{n}.json"},
                self.work / f"diagnosis-{n}.json", check=lambda d: d.get("category") in ("code", "workflow", "infra", "flaky"))
            diag = load_json(self.work / f"diagnosis-{n}.json")
            self.state.stage(f"{failed[0]} failed", "pipeline", n, cost, diag["category"], usage)
            cat = diag["category"]
            if cat in ("flaky", "infra") and diag.get("retry_recommended") and retries > 0:
                retries -= 1
                if failed[1]:
                    self.gh(["run", "rerun", str(failed[1]["databaseId"]), "--repo", self.app_repo, "--failed"], check=False)
                time.sleep(20)
                continue
            if cat == "code" and diag.get("fix_request") and fixes < self.lim["pipeline_fix_attempts"]:
                fixes += 1
                sha = self.coder(f"fix{fixes}", diag["fix_request"], str(self.work / "findings-none.json"))
                continue
            raise NeedsHuman("pipeline", f"{failed[0]} failed ({cat}): {diag.get('summary', '')[:500]}")

    # --- review + test

    def fast_review(self, base, head, rnd, share):
        """The reviewer as one model call over a prompt the Orchestrator assembles (no tools, no
        exploring). Returns (document, cost, usage) like agent_json, or raises ContextTooLarge or
        FastReviewFailed, in which case the caller uses the exploring Agent."""
        self.check_limits()
        role = self.cfg["roles"]["reviewer"]
        context = build_review_context(lambda *a: self.git(*a, check=False).stdout, base, head,
                                       self.lim.get("review_context_max_chars", 200000),
                                       spec=self.spec if getattr(self, "update_intake", False) else None)
        system = render(load_prompt(role["fast_prompt"]), {"app_name": self.app, "build_kind": self.build_kind, "base_sha": base[:8], "head_sha": head[:8]})
        with self.lock:
            jwt = self.meter.mint(role["model"], share)
        start = time.time()
        try:
            doc, u = single_call_review(self.cfg["provider"]["base_url"], jwt, role["model"], system, context)
        finally:
            self.record_spend(jwt)
        cost = self.meter.tokens[jwt]
        (self.work / f"verdict-{rnd}.json").write_text(json.dumps(doc, indent=2))
        prompt_tokens = u.get("prompt_tokens", 0)
        usage = {"calls": 1, "condenser_calls": 0, "peak_context": prompt_tokens, "last_context": prompt_tokens,
                 "prompt_tokens": prompt_tokens, "completion_tokens": u.get("completion_tokens", 0), "cache_read_tokens": 0}
        with self.lock:
            log(f"reviewer (r{rnd}) single call: {time.time() - start:.0f}s, {prompt_tokens:,} prompt and "
                f"{usage['completion_tokens']:,} output tokens, cost ${cost:.4f}")
        return doc, cost, usage

    def review_and_test(self, base, head, rnd):
        """The reviewer reads the code and the tester drives the deployed app (every round: a first
        build without flags is tested against the Intake); neither needs the other's result, so they
        run at the same time. Each gets half of what is left of the
        budget, its own HOME (OpenHands keeps its conversations there) and, for the tester, its
        own checkout of `head`."""
        d = self.state.d
        d["review_passes"] = rnd
        self.restore_tree()
        base_flags = self.git("show", f"{base}:flags.json", check=False).stdout
        head_flags = self.git("show", f"{head}:flags.json", check=False).stdout
        flags = new_flag_slugs(base_flags, head_flags)
        share = 0.5
        tester_tree = self.work / f"tester-tree-{rnd}"
        role_mode = self.cfg["roles"]["reviewer"].get("mode", "agent")

        def review():
            if role_mode == "single_call":
                try:
                    return self.fast_review(base, head, rnd, share)
                except (ContextTooLarge, FastReviewFailed) as e:
                    with self.lock:
                        log(f"Single-call review not possible ({e}); using the exploring reviewer.")
            return self.agent_json(
                "reviewer", f"r{rnd}", {"base_sha": base, "head_sha": head, "verdict_path": self.work / f"verdict-{rnd}.json"},
                self.work / f"verdict-{rnd}.json", check=lambda doc: derive_review(doc) and None,
                home=self.work / f"home-reviewer-{rnd}", share=share)

        def test():
            self.git("worktree", "add", "--detach", str(tester_tree), head)
            try:
                return self.agent_json(
                    "tester", f"t{rnd}", {"app_url": f"https://{self.app}.fly.dev", "head_sha": head,
                                          "report_path": self.work / f"test-report-{rnd}.json",
                                          "previous_report": previous_report(self.work, rnd), "api_check": getattr(self, "api_check_path", API_CHECK)},
                    self.work / f"test-report-{rnd}.json",
                    {"PREVIEW_TOKEN": self.preview, "API_CHECK_BASE": f"https://{self.app}.fly.dev",
                     "API_CHECK_LOG": str(self.work / f"api-check-{rnd}.jsonl")},
                    check=lambda doc: derive_test(doc, flags) and None,
                    cwd=tester_tree, home=self.work / f"home-tester-{rnd}", share=share)
            finally:
                self.git("worktree", "remove", "--force", str(tester_tree), check=False)

        with ThreadPoolExecutor(max_workers=2) as pool:
            review_job = pool.submit(review)
            test_job = pool.submit(test)
        # The pool has waited for both. Collect the reviewer first, then the tester, so a failure
        # in one still lets the other's cost reach the state.
        errors = []
        try:
            reviewer_doc, cost, usage = review_job.result()
            self.restore_tree()
            clean, blocking, minor = derive_review(reviewer_doc)
            self.state.stage("Review", "reviewer", rnd, cost, "clean" if clean else f"{len(blocking)} blocking", usage)
        except Exception as e:  # noqa: BLE001 - re-raised below, after the tester is recorded
            errors.append(e)
        test_failures, tpassed = [], True
        try:
            tdoc, cost, usage = test_job.result()
            tdoc = reconcile_api_checks(tdoc, load_api_results(self.work / f"api-check-{rnd}.jsonl"))
            try:  # so the next round's tester sees the failures the helper added; best effort, never a reason to stop the run
                (self.work / f"test-report-{rnd}.json").write_text(json.dumps(tdoc, indent=2))
            except OSError as e:
                log(f"could not rewrite the reconciled test report: {e}")
            tpassed, test_failures = derive_test(tdoc, flags)
            self.state.d["verification"] = {"round": rnd, "sha": head, **verification_record(tdoc, flags)}
            self.state.stage("Test", "tester", rnd, cost, "passed" if tpassed else f"{len(test_failures)} failed", usage)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        if errors:
            raise errors[0]
        all_blocking = (
            [finding_view("reviewer", f.get("summary", ""), f.get("evidence", ""), f) for f in blocking]
            + [finding_view("tester", f"{r.get('flag')}: {r.get('check')}", r.get("evidence", ""), r) for r in test_failures])
        self.state.d["blocking"] = all_blocking
        self.state.save()
        findings = {"round": rnd, "blocking": all_blocking,
                    "minor": [finding_view("reviewer", f.get("summary", ""), f.get("evidence", ""), f) for f in minor]}
        return clean, tpassed, flags, findings

    def gb(self, method, path, body=None):
        return http(method, f"{GROWTHBOOK_API}{path}", os.environ["GROWTHBOOK_ADMIN_PAT"], body)

    def release(self, flags, head):
        project = self.gb("GET", "/projects?limit=100")[1]["projects"][0]["id"]
        released, kept = [], []
        for slug in flags:
            if not SLUG_RE.fullmatch(slug):
                raise NeedsHuman("other", f"flag slug {slug!r} is not a valid slug; nothing released")
        for slug in flags:
            key = f"{self.app}.feature.{slug}"
            if self.gb("GET", f"/features/{key}")[0] == 200:
                kept.append(key)  # never re-enable or alter an existing flag
                continue
            status, r = self.gb("POST", "/features", {
                "id": key, "owner": "ai-factory", "valueType": "boolean", "defaultValue": "true", "project": project,
                "environments": {"production": {"enabled": True, "rules": []}}})
            if status != 200:
                raise RuntimeError(f"creating flag {key} failed: HTTP {status} {r}")
            released.append(key)
        body = (f"**Released** by Build Run [{self.run_id}]({self.run_url}) for commit `{head}`.\n\n"
                f"Enabled for everyone: {', '.join(f'`{k}`' for k in released) or 'none'}.\n"
                + (f"Left untouched (already existed): {', '.join(f'`{k}`' for k in kept)}.\n" if kept else "")
                + "\nRoll back by turning the flag off in GrowthBook.")
        self.gh(["api", f"repos/{self.app_repo}/commits/{head}/comments", "-f", f"body={body}"])
        self.state.d["release"] = {"released": released, "kept": kept}
        self.state.stage("Release", "-", "-", 0, f"{len(released)} flag(s) released")

    def record_round(self, rnd, head, blocking):
        """Add this round to the scoreboard (state.json, so it reaches the Report, and artifacts/progress.json)."""
        record = self.state.d.get("verification")
        if not record or record.get("round") != rnd:
            record = {"round": rnd, "sha": head, "counts": {s: 0 for s in CHECK_STATES}, "checks": [], "limitations": []}
        self.state.d["scoreboard"].append(scoreboard_entry(rnd, head, record, blocking))
        self.state.save()
        (self.art / "progress.json").write_text(json.dumps(self.state.d["scoreboard"], indent=2))

    def app_error_count(self):
        try:
            p = sh(["flyctl", "logs", "--no-tail", "--app", self.app],
                   env={**os.environ, "FLY_API_TOKEN": os.environ.get("FLY_API_TOKEN", "")}, check=False, timeout=120)
            return count_errors(p.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            return 0

    def disable_flags(self, keys):
        """Switch flags off in production and read each back. Returns the keys that are still on."""
        still_on = []
        for key in keys:
            self.gb("POST", f"/features/{key}", {"environments": {"production": {"enabled": False, "rules": []}}})
            status, r = self.gb("GET", f"/features/{key}")
            env = ((r.get("feature") or r) if isinstance(r, dict) else {}).get("environments", {}).get("production", {})
            if status != 200 or env.get("enabled") is not False:
                still_on.append(key)
        return still_on

    def watch_release(self):
        """After a release, watch the app for `watchdog_minutes`. A run of failed health checks, or a
        rise in error-level log lines, switches the flags this run released off by itself (never one
        that already existed, which the owner controls) and ends the run as `watchdog_disabled` so
        finalize opens the Issue. The flag is the rollback lever, and the release step never turns
        it back on. 0 minutes disables the watch."""
        # The outcome was set just before this call and is not on disk yet. Save it now: the watch below can take
        # minutes, and a run cancelled during it must still report `released`, not look like a crash.
        self.state.save()
        keys = list((self.state.d.get("release") or {}).get("released") or [])
        minutes = float(self.lim.get("watchdog_minutes", 0))
        if minutes <= 0 or not keys:
            return
        interval = float(self.lim.get("watchdog_interval_seconds", 30))
        end = min(time.time() + minutes * 60, self.deadline)
        baseline = self.app_error_count()
        samples = []
        log(f"watching {self.app} for {minutes:g} minutes after the release")
        while time.time() < end:
            time.sleep(interval)
            status, _ = http("GET", f"https://{self.app}.fly.dev/api/health", timeout=20)
            samples.append({"healthy": status == 200, "errors": self.app_error_count()})
            reason = watchdog_trip(samples, baseline, int(self.lim.get("watchdog_max_failures", 3)),
                                   int(self.lim.get("watchdog_max_errors", 5)))
            if reason:
                still_on = self.disable_flags(keys)
                note = f" Could not confirm these are off: {', '.join(still_on)}; turn them off in GrowthBook now." if still_on else ""
                self.state.d.update(outcome="watchdog_disabled", message=(
                    f"Released {len(keys)} flag(s), then switched them off: {reason}.{note}"))
                self.state.stage("Watchdog", "-", "-", 0, "flags switched off")
                return
        self.state.stage("Watchdog", "-", "-", 0, f"clean for {minutes:g} min")

    def plan_change(self):
        """Plan an Update Intake with the planner Agent, then check the plan deterministically. Returns True when
        the request was split into several change sets and filed as child issues (this run is then finished), False
        when there is one change set, which becomes this run's task. A plan that fails the check, or that has a
        blocking question, stops the run for a person."""
        path = self.work / "plan.json"
        limit = int(self.lim.get("planner_max_change_sets", planner.MAX_CHANGE_SETS))
        problems = []

        def check(doc):
            found, _ = planner.validate_plan(doc, self.build_kind, limit)
            problems[:] = found
            if found:
                raise ValueError("; ".join(found))

        try:
            doc, cost, usage = self.agent_json("planner", "1", {"task": self.task, "plan_path": path}, path, check=check)
        except NeedsHuman:
            if problems:
                raise NeedsHuman("other", "the planner's plan was rejected: " + "; ".join(problems))
            raise
        _, questions = planner.validate_plan(doc, self.build_kind, limit)
        if questions and getattr(self, "fix_meta", None):
            # An automatic retry has no person to answer. Take the most conservative reading and say so, in the plan comment.
            doc["assumptions"] = list(doc.get("assumptions") or []) + [
                f"Decided without asking (this retry runs with no person reviewing it): {q} Taking the most conservative reading: "
                "keep existing data and behaviour, and keep the change behind its flag." for q in questions]
            questions = []
        sets = doc["change_sets"]
        self.state.d["plan"] = {"change_sets": [{"id": c["id"], "title": c["title"], "flag": c.get("flag")} for c in sets],
                                "assumptions": doc.get("assumptions") or []}
        self.state.stage("Plan", "planner", "1", cost, f"{len(sets)} change set(s)" + (", needs an answer" if questions else ""), usage)
        (self.art / "plan.json").write_text(json.dumps(doc, indent=2))
        self.post_plan(doc, questions)
        if questions:
            raise NeedsHuman("other", "the plan needs a person to answer first: " + " | ".join(questions)
                             + ". Put the answers in the Update Intake issue, then add `proceed-with-change` again.")
        if len(sets) == 1:
            self.task = update_intake.render_change_set_task(sets[0], request=self.task)
            self.spec = self.task
            return False
        made = update_intake.file_children(self.factory_repo, self.pat, self.app, int(self.issue), sets,
                                           planner.topological_order(sets), self.task, cap=self.cap_override)
        self.state.d.update(outcome="planned", message="Planned as %d change sets, each now its own Update Intake and Build Run, in order: %s."
                            % (len(made), ", ".join(f"{cs} (#{n})" for cs, n in made)))
        return True

    def post_plan(self, doc, questions):
        """Put the plan on the Intake issue, so the owner can see what is about to be built and every assumption the
        planner made (a product decision it made for them is otherwise only in a build artifact). Best effort."""
        try:
            body = update_intake.render_plan_comment(doc, questions)
            self.gh(["issue", "comment", str(self.issue), "--repo", self.factory_repo, "--body", body],
                    token=self.factory_token, check=False)
        except Exception as e:  # noqa: BLE001
            log(f"could not post the plan to the Intake issue: {type(e).__name__}")

    # --- the run

    def run(self):
        try:
            self.setup()
            if self.update_intake and not self.plan_meta and self.lim.get("planner_enabled", True):
                if self.plan_change():
                    return
            base = self.state.d["base_sha"]
            findings_path = self.work / "findings-0.json"
            findings_path.write_text(json.dumps({"blocking": [], "minor": []}))
            task = self.task
            head = self.coder("1", task, str(findings_path))
            for rnd in range(1, self.lim["review_rounds"] + 1):
                head = self.pipeline(head)
                self.state.d["head_sha"] = head
                clean, tpassed, flags, findings = self.review_and_test(base, head, rnd)
                # Kept on a clean pass too: the minor findings of a run that ships are what the post-mortem learns from.
                findings_path = self.work / f"findings-{rnd}.json"
                findings_path.write_text(json.dumps(findings, indent=2))
                self.record_round(rnd, head, findings["blocking"])
                if release_gate(True, True, tpassed, clean, head, self.head()):
                    self.check_limits()
                    if flags:
                        self.release(flags, head)
                        self.state.d.update(outcome="released", message=f"Released {len(flags)} flag(s).")
                        self.watch_release()
                    else:
                        self.state.d.update(outcome="nothing_to_release", message=(
                            "First build deployed and live; it has no flags to release." if self.build_kind == "first build"
                            else "Clean, but the update added no flag, so there was nothing to release."))
                    return
                if rnd == self.lim["review_rounds"]:
                    raise NeedsHuman("round_limit", f"{self.lim['review_rounds']} review rounds used without a clean pass")
                if stalled(self.state.d["scoreboard"], int(self.lim.get("stuck_rounds", 0))):
                    raise NeedsHuman("stuck", f"the last {self.lim['stuck_rounds']} rounds left the same checks failing and the "
                                              "same findings open; more fix rounds are not changing anything")
                summary = "\n".join(describe_finding(b) for b in findings["blocking"]) or "- (none; minor findings only)"
                head = self.coder(str(rnd + 1), f"Round {rnd + 1} fix list. Resolve every blocking item:\n{summary}", str(findings_path))
        except ProviderBlocked as e:
            self.state.d.update(outcome="provider_blocked", message=str(e))
        except BudgetExhausted as e:
            self.state.d.update(outcome="budget_exhausted", message=str(e))
        except NeedsHuman as e:
            outcome, message = ending_for(e.kind, str(e), self.state.d.get("spent_usd"), self.cap)
            self.state.d.update(outcome=outcome, message=message)
        except Exception as e:  # noqa: BLE001 - any crash must still reach finalize
            traceback.print_exc()
            self.state.d.update(outcome="crash", message=f"{type(e).__name__}: {e}")
        finally:
            self.state.save()
        return


# --- finalize -------------------------------------------------------------------

OUTCOME_TITLES = {
    "budget_exhausted": "Build Run: budget exhausted",
    "round_limit": "Build Run: needs human (review round limit reached)",
    "time_limit": "Build Run: needs human (time limit reached)",
    "provider_blocked": "Build Run: model provider blocked (account has no balance)",
    "stuck": "Build Run: needs human (no progress across rounds)",
    "watchdog_disabled": "Build Run: release switched off by the watchdog",
    "needs_human": "Build Run: needs human",
    "crash": "Build Run: crash",
    "running": "Build Run: crash (it ended without finishing)",
}


def render_summary(d):
    icon = ":white_check_mark:" if d["outcome"] in OK_OUTCOMES else ":x:"
    lines = [f"## Build Run Summary: {d['app']}", "",
             f"**Status**: {icon} `{d['outcome']}`  ", f"**Message**: {d['message'] or '-'}  ",
             f"**Cost**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f} cap  ",
             f"**Review passes**: {d['review_passes']}  ", f"**Final commit**: `{d['head_sha'] or '-'}`  ",
             f"**App**: https://{d['app']}.fly.dev  ", f"**Fly log viewer**: https://fly.io/apps/{d['app']}/monitoring", "",
             "| Stage | Agent | Round | Cost | Time (model) | Calls | Peak context | Tokens in (cached) | Tokens out | Condenser calls | Verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    goal = d.get("context_goal_tokens", 100000)
    peaks = []
    for s in d["stages"]:
        u = s.get("usage")
        if u:
            peaks.append((u["peak_context"], f"{s['agent']} {s['round']}"))
            peak = f"{u['peak_context']:,}" + (" :warning:" if u["peak_context"] > goal else "")
            cols = [f"{u.get('seconds', 0):.0f}s ({u.get('llm_seconds', 0):.0f}s)", str(u["calls"]), peak, f"{u['prompt_tokens']:,} ({u['cache_read_tokens']:,})",
                    f"{u['completion_tokens']:,}", str(u["condenser_calls"])]
        else:
            cols = ["-"] * 6
        lines.append(f"| {s['stage']} | {s['agent']} | {s['round']} | ${s['cost_usd']:.4f} | {' | '.join(cols)} | {s['verdict']} |")
    if peaks:
        top, who = max(peaks)
        verdict = "over the goal" if top > goal else "under the goal"
        lines += ["", f"**Peak context this run**: {top:,} tokens ({who}), {verdict} of {goal:,}. "
                  "A peak is the largest prompt in a single LLM call, i.e. how big one Agent's context got."]
    rev = d.get("revert")
    if rev and rev.get("status") != "skipped":
        lines += ["", "**Revert**: " + (f"`main` restored to `{str(rev.get('restored', ''))[:8]}` in `{str(rev.get('sha', ''))[:8]}`; deploy {rev.get('deploy', 'not checked')}."
                                      if rev["status"] == "reverted" else f"{rev['status']}: {rev.get('reason', '')}")]
    ver = d.get("verification")
    if ver:
        c = ver["counts"]
        lines += ["", f"**Verification** (round {ver['round']}, `{str(ver['sha'])[:8]}`): {c['passed']} passed, {c['failed']} failed, "
                  f"{c['blocked']} blocked, {c['not_run']} not run."]
        if ver.get("limitations"):
            lines += ["", "**Not tested or not cleaned up (limitations)**:"] + [f"- {x}" for x in ver["limitations"]]
    if d.get("audit"):
        lines += audit.render_audit(d["audit"]).rstrip("\n").split("\n")
    board = d.get("scoreboard") or []
    if len(board) > 1:
        lines += ["", "**Scoreboard** (checks passed / failed / blocked / not run, blocking findings open):"]
        lines += [f"- round {e['round']}: {e['counts']['passed']} / {e['counts']['failed']} / {e['counts']['blocked']} / "
                  f"{e['counts']['not_run']}, {len(e['blocking'])} open" for e in board]
    rel = d.get("release")
    lines += ["", "**Release**: " + (f"released {', '.join(rel['released']) or 'nothing new'}" if rel else "not released")]
    if d["blocking"] and d["outcome"] not in OK_OUTCOMES:
        lines += ["", "**Open blocking findings at the end**:"] + [f"- [{b['source']}] {b['summary']}" for b in d["blocking"]]
    return "\n".join(lines) + "\n"


def record_spend_in_ledger(d, repo, run_id, token):
    """Add this run's spend to the ledger issue (best effort: a failure here never changes the run's outcome)."""
    try:
        if not d.get("spent_usd"):
            return
        env = {**os.environ, "GH_TOKEN": token}
        out = sh(["gh", "issue", "list", "--repo", repo, "--label", LEDGER_LABEL, "--state", "open", "--json", "number"],
                 env=env, check=False).stdout
        found = json.loads(out or "[]")
        if not found:
            sh(["gh", "label", "create", LEDGER_LABEL, "--repo", repo, "--color", "ededed",
                "--description", "One comment per Build Run with what it spent"], env=env, check=False)
            made = sh(["gh", "issue", "create", "--repo", repo, "--label", LEDGER_LABEL, "--title", "Factory spend ledger", "--body",
                       "One comment per finished Build Run (`ledger <date> <app> <usd> run:<id>`). The Orchestrator adds the day's "
                       "lines to check `limits.daily_cost_cap_usd`. Do not edit or close this issue."], env=env, check=False).stdout
            m = re.search(r"/issues/(\d+)", made)
            found = [{"number": int(m.group(1))}] if m else []
        if found:
            sh(["gh", "issue", "comment", str(found[0]["number"]), "--repo", repo, "--body",
                ledger_line(time.strftime("%Y-%m-%d", time.gmtime()), d["app"], d["spent_usd"], run_id)], env=env, check=False)
    except Exception as e:  # noqa: BLE001
        print(f"could not record spend in the ledger: {type(e).__name__}", flush=True)


def update_state_issues(d, factory_repo, pat, factory_token):
    """Rewrite the app's State issue and ai-factory's registry issue after a run (best effort)."""
    import tempfile
    try:
        owner, app = factory_repo.split("/")[0], d["app"]
        app_repo = f"{owner}/{app}"

        def gh(args, token):
            return sh(["gh", *args], env={**os.environ, "GH_TOKEN": token}, check=False).stdout

        def upsert(repo, token, label, title, color, render):
            found = json.loads(gh(["issue", "list", "--repo", repo, "--label", label, "--state", "open",
                                   "--json", "number,body,url"], token) or "[]")
            prev = found[0]["body"] if found else ""
            body = render(prev)
            if found:
                number, url = found[0]["number"], found[0]["url"]
                with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                    f.write(body)
                gh(["issue", "edit", str(number), "--repo", repo, "--body-file", f.name], token)
                return url
            gh(["label", "create", label, "--repo", repo, "--color", color, "--description", "Maintained by the Orchestrator"], token)
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                f.write(body)
            made = gh(["issue", "create", "--repo", repo, "--label", label, "--title", title, "--body-file", f.name], token)
            m = re.search(r"https://\S+/issues/(\d+)", made)
            if m:
                gh(["issue", "pin", m.group(1), "--repo", repo], token)  # best effort; not every plan allows it
            return m.group(0) if m else ""

        state_url = upsert(app_repo, pat, appstate.STATE_LABEL, "Factory: app state", "5319e7", lambda prev: appstate.render_state(prev, d))
        upsert(factory_repo, factory_token, appstate.REGISTRY_LABEL, "Factory: Managed Apps", "5319e7",
               lambda prev: appstate.render_registry(prev, d, state_url))
    except Exception as e:  # noqa: BLE001
        print(f"could not update the state issues: {type(e).__name__}", flush=True)


NEAR_CAP = 0.9  # an Agent is given only a share of what is left, so a run runs dry a little before the cap itself


BLOCKED_MESSAGE = ("The model provider refused the request because the account has no balance (HTTP 402, \"You need positive balance to "
                   "do inference\"). Add balance (or turn on auto top-up) in the provider's dashboard, then add `proceed-with-change` "
                   "again to retry.")
BLOCKED_LINE_RE = re.compile(r"positive balance|insufficient (funds|balance|credits?)|payment required", re.I)
BLOCKED_EVENT_RE = re.compile(r"BadRequestError|ConversationErrorEvent|LLMError|\b402\b")


def provider_blocked_text(text):
    """True if some line of an Agent's output is an error from the provider saying the account has no balance. Both parts
    are needed on one line (an error event and the billing wording), so a prompt or a log that merely mentions balances
    does not trip it."""
    return any(BLOCKED_LINE_RE.search(line) and BLOCKED_EVENT_RE.search(line) for line in (text or "").splitlines())


def scan_for_provider_block(path, tail_bytes=300_000):
    """BLOCKED_MESSAGE if the end of an Agent's JSONL output shows the provider refusing for lack of balance, else None."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            text = f.read().decode(errors="replace")
    except OSError:
        return None
    return BLOCKED_MESSAGE if provider_blocked_text(text) else None


def provider_check(base_url, key, model):
    """A one-token request before a Build Run does any work: raises ProviderBlocked if the account has no balance, so a run
    cannot spend a clone, a checkout and a planner call to find out. Any other answer (including an outage) is not this
    condition and is left for the run to deal with."""
    status, r = http("POST", f"{base_url}/chat/completions", key,
                     {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}, timeout=30)
    if status == 402 or (status == 400 and provider_blocked_text(f"BadRequestError {r}")):
        raise ProviderBlocked(BLOCKED_MESSAGE)


def ending_for(kind, message, spent, cap):
    """How a NeedsHuman stop is reported. An Agent whose credential has run dry just fails to produce its file (first seen
    when a tester ran out of a $0.08 cap and the run was reported as `needs_human: no valid output file`), so a stop of
    kind `other` with the cap already spent is a budget ending, not a mystery."""
    named = {"time_limit": "time_limit", "round_limit": "round_limit", "stuck": "stuck"}.get(kind)
    if named:
        return named, message
    if cap and spent is not None and spent >= NEAR_CAP * cap:
        return "budget_exhausted", f"${spent:.4f} spent against a ${cap:.2f} cap, and then: {message}"
    return "needs_human", message


def revert_decision(d, mode, flags_added=()):
    """(revert, reason). A Build Run that ends badly leaves the commits it pushed on `main`, and every push deploys.
    Flagged commits are dark, but unflagged ones (a retirement, a refactor, a first build) are live. So a bad ending
    puts `main` back where the run found it. `mode` is `all`, `unflagged` (only runs that added no flag) or `off`."""
    outcome, commits = d.get("outcome"), d.get("commits") or []
    if mode == "off":
        return False, "reverting failed runs is switched off"
    if outcome in OK_OUTCOMES:
        return False, "the run ended well"
    if outcome == "watchdog_disabled" or (d.get("release") or {}).get("released"):
        return False, "contained: the flags it released are switched off, or it released and its state was not saved"
    if not commits:
        return False, "the run pushed nothing"
    if not d.get("base_sha") or not d.get("head_sha") or d["base_sha"] == d["head_sha"]:
        return False, "there is no earlier state to return to"
    if mode == "unflagged" and flags_added:
        return False, "flagged: its code is dark until released"
    return True, ""


def revert_main_to_base(d, app_dir, git_auth=None, run_id="0"):
    """Put `main` back to the run's starting tree with one new commit on top (history is kept, so there are no conflicts to
    resolve and nothing is force-pushed). Skips, and says why, if `main` has moved on since the run's last push: someone
    else's commit is there and is not ours to overwrite. Returns {"status": reverted|skipped|failed, ...}."""
    base, head = d["base_sha"], d["head_sha"]
    git = lambda *a, check=True: sh(["git", *a], cwd=app_dir, env={**os.environ, **(git_auth or {})}, check=check)
    try:
        git("fetch", "-q", "origin", "main")
        remote = git("rev-parse", "origin/main").stdout.strip()
        if remote != head:
            return {"status": "skipped", "reason": f"main is at {remote[:8]}, not at the run's last push {head[:8]}; not reverting over it"}
        git("reset", "-q", "--hard")
        git("clean", "-fdq")
        git("checkout", "-q", "-B", f"revert-{run_id}", "origin/main")
        git("read-tree", "--reset", "-u", base)
        if git("diff", "--cached", "--quiet", "HEAD", check=False).returncode == 0:
            return {"status": "skipped", "reason": "main already has the starting tree"}
        git("-c", "user.name=ai-factory-orchestrator", "-c", "user.email=orchestrator@ai-factory.local", "commit", "-q", "-m",
            f"Revert Build Run {run_id} ({d.get('outcome')}): restore {base[:8]}\n\n{d.get('message') or ''}\n\n"
            f"The run pushed {len(d.get('commits') or [])} commit(s) and did not reach a clean pass, so its changes were taken back out. "
            "They remain in the history.")
        git("push", "-q", "origin", "HEAD:main")
        return {"status": "reverted", "sha": git("rev-parse", "HEAD").stdout.strip(), "restored": base}
    except Exception as e:  # noqa: BLE001 - reported, never raised: finalize must still write its Report
        return {"status": "failed", "reason": f"{type(e).__name__}: {str(e)[:300]}"}


def wait_for_revert_deploy(app, app_repo, sha, pat, minutes):
    """After a revert push: wait for the app's deploy of that commit and for /api/health. 'healthy', 'deploy_failed' or 'timeout'."""
    env = {**os.environ, "GH_TOKEN": pat}
    end = time.time() + minutes * 60
    while time.time() < end:
        out = sh(["gh", "run", "list", "--repo", app_repo, "--workflow", "deploy-fly.yml", "--limit", "10", "--json",
                  "headSha,status,conclusion"], env=env, check=False).stdout
        runs = [r for r in json.loads(out or "[]") if r.get("headSha") == sha and r.get("status") == "completed"]
        if any(r.get("conclusion") == "success" for r in runs):
            status, _ = http("GET", f"https://{app}.fly.dev/api/health", timeout=20)
            if status == 200:
                return "healthy"
        elif runs:
            return "deploy_failed"
        time.sleep(20)
    return "timeout"


def revert_failed_run(d, app_dir, pat, lim):
    """The finalize step: decide, revert, wait for the deploy, and record the outcome in the Report as d["revert"]."""
    mode = str(lim.get("revert_failed_runs", "all"))
    flags_added = []
    if d.get("base_sha") and d.get("head_sha") and Path(app_dir).is_dir():
        git = lambda *a: sh(["git", *a], cwd=app_dir, check=False).stdout
        flags_added = new_flag_slugs(git("show", f"{d['base_sha']}:flags.json"), git("show", f"{d['head_sha']}:flags.json"))
    go, why = revert_decision(d, mode, flags_added)
    if not go:
        d["revert"] = {"status": "skipped", "reason": why, "mode": mode}
        return
    if not Path(app_dir).is_dir():
        d["revert"] = {"status": "failed", "reason": "the app checkout is not there", "mode": mode}
        return
    auth = git_auth_env("Authorization: Basic " + base64.b64encode(f"x-access-token:{pat}".encode()).decode())
    d["revert"] = {**revert_main_to_base(d, app_dir, auth, os.environ.get("GITHUB_RUN_ID", "0")), "mode": mode}
    if d["revert"]["status"] == "reverted":
        owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
        d["revert"]["deploy"] = wait_for_revert_deploy(d["app"], f"{owner}/{d['app']}", d["revert"]["sha"], pat,
                                                       float(lim.get("revert_deploy_timeout_minutes", 15)))


def finish_update_intake(ok, repo, number, pat):
    """An Update Intake that finished is closed and starts the change sets waiting on it; one that stopped loses
    `proceed-with-change`, so adding the label again retries it (a label that is still there cannot fire again)."""
    try:
        env = {**os.environ, "GH_TOKEN": pat}
        if ok:
            sh(["gh", "issue", "close", str(number), "--repo", repo, "--reason", "completed"], env=env, check=False)
            update_intake.advance(repo, pat, number)
        else:
            sh(["gh", "issue", "edit", str(number), "--repo", repo, "--remove-label", update_intake.GO], env=env, check=False)
    except Exception as e:  # noqa: BLE001
        print(f"could not finish the Update Intake: {type(e).__name__}", flush=True)


def finalize():
    work = Path(os.environ["BUILD_RUN_DIR"])
    app = os.environ["APP_NAME"]
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '0')}"
    d = load_json(work / "state.json")
    if d is None:
        d = {"app": app, "issue_number": os.environ["ISSUE_NUMBER"], "run_url": run_url, "outcome": "crash",
             "message": "no state file was written; the Build Run failed before its first stage", "cap_usd": 0,
             "spent_usd": 0.0, "head_sha": None, "review_passes": 0, "stages": [], "release": None, "blocking": [],
             "commits": [], "base_sha": None}
    elif d["outcome"] == "running":
        d["message"] = d["message"] or "the Build Run process ended without recording an outcome (cancelled or killed)"
    d["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        revert_failed_run(d, os.environ.get("APP_DIR", ""), os.environ["FACTORY_PAT"], load_config()["limits"])
    except Exception as e:  # noqa: BLE001
        d["revert"] = {"status": "failed", "reason": f"{type(e).__name__}: {str(e)[:300]}"}
    d["audit"] = audit.audit_report(d)
    # The post-mortem reads state.json, so the final state (audit, revert) has to be saved there too.
    (work / "state.json").write_text(json.dumps(d, indent=2))
    summary = render_summary(d)
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    (work / "artifacts" / "build-run-report.json").write_text(json.dumps(d, indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a") as f:
        f.write(summary)
    ok = d["outcome"] in OK_OUTCOMES
    record_spend_in_ledger(d, os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_RUN_ID", "0"), os.environ["FACTORY_GH_TOKEN"])
    pat, ftoken = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    update_state_issues(d, os.environ["GITHUB_REPOSITORY"], pat, ftoken)
    if not ok:
        body = f"{d['message']}\n\n**Build Run**: {run_url}\n**Spent**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f}\n\n" + summary
        (work / "issue-body.md").write_text(body)
        sh(["gh", "issue", "create", "--repo", f"{owner}/{app}", "--title", OUTCOME_TITLES.get(d["outcome"], "Build Run: crash"),
            "--body-file", str(work / "issue-body.md")], env={**os.environ, "GH_TOKEN": pat}, check=False)
    retry = ("" if ok or d.get("intake_kind") != "update" else
             f"\n\nOnce the provider balance is topped up, add `{update_intake.GO}` again to retry." if d["outcome"] == "provider_blocked"
             else f"\n\nEdit this issue if the request needs to change, then add `{update_intake.GO}` again to retry.")
    sh(["gh", "issue", "comment", d["issue_number"], "--repo", os.environ["GITHUB_REPOSITORY"], "--body",
        f"**Build Run {'finished' if ok else 'stopped'}: `{d['outcome']}`.** {d['message']} ([run]({run_url})){retry}"],
       env={**os.environ, "GH_TOKEN": ftoken}, check=False)
    if d.get("intake_kind") == "update":
        finish_update_intake(ok, os.environ["GITHUB_REPOSITORY"], d["issue_number"], pat)
    return 0 if ok else 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        BuildRun().run()
        return 0
    if cmd == "finalize":
        return finalize()
    print("usage: build_run.py run|finalize", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
