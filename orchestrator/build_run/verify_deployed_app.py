# STEP 4.9 and 4.10: the tester against the deployed app, reconciling its report with what the helpers observed, the verdict, `test_impact` and bugs.
import json
import os
import re

from shared import (
    config,
    run_stops,
)
from shared.console import log

from build_run import track_progress

API_CHECK = str(config.FACTORY_DIR / "orchestrator" / "shared" / "api_check.py")  # the helper the tester calls (see api_check.py)


UI_CHECK = str(config.FACTORY_DIR / "orchestrator" / "build_run" / "ui_check.py")  # its browser counterpart (see ui_check.py)


# Evidence that says, in the tester's own words, that it did not observe the thing it is reporting on. A model that writes
# this and still marks the check `passed` (seen in the first real run on an unobservable requirement) has not verified it.
UNOBSERVED_RE = re.compile(
    r"\b(unable to|not able to|cannot|can't|could not|couldn't|did not|didn't|no way to|no access to)\s+(directly\s+)?"
    r"(observe|verify|see|view|read|check|confirm|access|inspect|determine|validate)\b|\bunverifi(able|ed)\b|\bnot (been )?(verified|observed)\b", re.I)


RAN_A_TEST_RE = re.compile(r"\b(npm (run )?test|vitest|jest|unit test|test file|test suite|tests? (pass|passed|asserts?))\b", re.I)


def admits_unobserved(evidence):
    # True if the evidence says the thing was not observed, unless it also points at a test that was run for it.
    text = str(evidence or "")
    return bool(UNOBSERVED_RE.search(text)) and not RAN_A_TEST_RE.search(text)


def check_state(r):
    # One tester result's state. `status` is one of CHECK_STATES; a report that only has the older
    # boolean `passed` is read as passed or failed. Anything unrecognised counts as failed. A check marked `passed`
    # whose own evidence admits it was not observed counts as `not_run`: it keeps the change from releasing.
    if not isinstance(r, dict):
        return "failed"
    state = r["status"] if r.get("status") in track_progress.CHECK_STATES else ("passed" if r.get("passed") is True else "failed")
    if state == "passed" and admits_unobserved(r.get("evidence")):
        return "not_run"
    return state


def load_api_results(path):
    # The api-check helper's own log (one JSON line per check it ran) as {id: result}; the last result for an id wins.
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


def _helper_ids(result, field):
    ids = result.get(field)
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else ([ids] if isinstance(ids, str) else [])


def reconcile_helper_checks(doc, found, field, label):
    # The tester's report with a helper's observations ranking above its judgement. A result that cites a check (in `field`, `api`
    # or `ui`) which failed cannot stay `passed`; one that cites a check the helper never ran cannot either; and a check the helper saw
    # fail that no result mentions is added as a failure, so the tester cannot leave out what it was shown. Results that cite no check of
    # this kind are untouched.
    results = [dict(r) for r in (doc.get("results") if isinstance(doc, dict) else None) or [] if isinstance(r, dict)]
    cited = set()
    for r in results:
        ids = _helper_ids(r, field)
        cited.update(ids)
        failing = [i for i in ids if i in found and not found[i].get("ok")]
        unknown = [i for i in ids if i not in found]
        if check_state(r) != "passed":
            continue
        if failing:
            r.update(status="failed", passed=False, evidence=(f"{r.get('evidence', '')} | the {label} helper observed otherwise: "
                     + "; ".join(f"{i}: {'; '.join(found[i].get('problems') or ['failed'])}" for i in failing)).strip(" |"))
        elif unknown:
            r.update(status="not_run", passed=False, evidence=(f"{r.get('evidence', '')} | cites {label} id(s) the helper never ran: "
                     + ", ".join(unknown)).strip(" |"))
    flag = next((r.get("flag") for r in results if r.get("flag")), "")
    for i, res in found.items():
        if not res.get("ok") and i not in cited:
            observed = res.get("observed") or {}
            seen = f" (status {observed.get('status')})" if "status" in observed else ""
            results.append({"flag": flag, "check": f"{label} {i}: {res.get('name', i)}", "status": "failed", "passed": False, field: [i],
                            "evidence": f"the {label} helper observed a failure the report did not mention: "
                                        + "; ".join(res.get("problems") or ["failed"]) + seen})
    return {**doc, "results": results}


def report_from_helper_failures(api, ui):
    # A tester report built only from what the helpers saw fail, for when the tester wrote none. None when nothing failed: with no
    # report and no failure there is nothing to act on, and the run stops for a person as before.
    if all(r.get("ok") for r in list(api.values()) + list(ui.values())):
        return None
    doc = {"passed": False, "results": [], "limitations": ["the tester wrote no report; these failures come from the helpers' own logs, and nothing else was assessed"]}
    return reconcile_ui_checks(reconcile_api_checks(doc, api), ui)


def reconcile_api_checks(doc, api):
    return reconcile_helper_checks(doc, api, "api", "api-check")


def reconcile_ui_checks(doc, ui):
    return reconcile_helper_checks(doc, ui, "ui", "ui-check")


UI_WORDS = re.compile(r"\b(page|screen|button|link|menu|modal|dialog|ui|frontend|front-end|label|form field|input field|dropdown|checkbox)\b", re.I)


def wants_ui_check(changed_files, spec):
    # True when the change touches the frontend or the spec talks about something a person sees on screen.
    return any(str(f).startswith("frontend/") for f in changed_files) or bool(UI_WORDS.search(spec or ""))


def ui_section(wanted, helper_path):
    # The tester prompt's browser instructions, or an empty string when this change has nothing to see.
    if not wanted:
        return ""
    return (f"This change has something on screen, so also check it in a browser with the `ui-check` helper (a headless Chromium): write the "
            f"scenarios into a file and run `python3 {helper_path} ui-checks.json`. The base URL and the token are already set. A scenario is a "
            "`start` path, `auth` (`\"preview\"` opens the page with the Preview Token, so a dark UI change shows; `\"none\"` is an ordinary "
            "visitor), `steps` (`click`, `fill` with a `value`, `press`, `goto`, `wait_for`, `check`, `select`) and an `expect` of what must be "
            "on the page afterwards: `visible`, `hidden`, `text` (with `contains` or `equals`), `count` (with `is`), `url_path`, "
            "`title_contains`, `no_console_errors`. Find things the way a user does: `{\"role\": \"button\", \"name\": \"Add\"}`, "
            "`{\"label\": \"New todo\"}`, `{\"text\": \"...\"}`, `{\"placeholder\": \"...\"}` or `{\"test_id\": \"...\"}`. Take every expected "
            "label and text from the spec word for word, and check both sides of a flagged control: hidden with `auth: none`, visible with "
            "`auth: preview`. The helper, not you, decides pass or fail, and the Orchestrator reads its log, so a scenario it saw fail cannot be "
            "reported as passed. Cite the scenario ids a result rests on in its `ui` list. The helper waits a few seconds for each expectation "
            "(a page updates after a network call), so add no sleeps. Budget: run the file once, and a second time only to fix a mistake in your "
            "own scenarios; do not read the app's source to explain a failure, report what the helper observed. The app is live and shared: "
            "give each scenario its own record named `factory-test-<scenario>`, delete what you created afterwards, and never assert that a "
            "list is empty or that someone else's records are gone (mark that check `not_run` and say why). Whatever happens, finish by writing "
            "the report: a report with failures is useful, no report stops the run. Example: `{\"checks\": [{\"id\": \"add\", \"name\": \"Adding a todo shows it\", \"auth\": \"preview\", "
            "\"steps\": [{\"fill\": {\"label\": \"New todo\", \"value\": \"factory-test-a\"}}, {\"click\": {\"role\": \"button\", \"name\": \"Add\"}}], "
            "\"expect\": {\"text\": [{\"role\": \"listitem\", \"contains\": \"factory-test-a\"}]}}]}`.")


def derive_test(doc, expected_flags):
    # (passed, failures). passed is derived from the results, and every new flag needs a result.
    # Only a check in the `passed` state passes: `failed`, `blocked` (something outside the app stopped
    # the check) and `not_run` all keep the change from releasing. With no new flags (a first build)
    # the results test the Intake's requirements, and there must be at least one.
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


def test_impact(failures):
    # What a test pass that did not pass means for production: `regression` when a check of behaviour released *before* this change
    # (`scope: existing`) failed and a helper observed it (the helper's log, not the model's word, is what makes it a regression),
    # `dark_only` when only the new, still-dark change fails, `ok` when nothing failed. A regression is the one case that takes
    # the live app back on the previous deployed version (never a git revert); a broken dark feature stays dark and is fixed forward.
    if not failures:
        return "ok"
    for r in failures:
        if isinstance(r, dict) and r.get("scope") == "existing" and check_state(r) == "failed" and (r.get("api") or r.get("ui")):
            return "regression"
    return "dark_only"


MAX_BUGS = 10


def failed_checks(failures):
    # The checks the tester saw fail, which the coder can act on. A check that was `blocked` (something outside the app stopped it) or
    # `not_run` was not seen to fail, and sending it to the coder as a fix costs a round for something it cannot change.
    return [r for r in failures if isinstance(r, dict) and check_state(r) == "failed"]


def unverified_message(failures):
    states = {}
    for r in failures:
        if isinstance(r, dict):
            states[check_state(r)] = states.get(check_state(r), 0) + 1
    names = "; ".join(str(r.get("check") or "?")[:80] for r in failures[:3] if isinstance(r, dict))
    return (f"{len(failures)} check(s) could not be verified ({', '.join(f'{n} {k}' for k, n in sorted(states.items()))}), and none failed, "
            f"so another coder round cannot help. Unverified: {names}")


def bugs_from(failures):
    # The tester's failed checks as notes for the retrospective, which adds them to the story's own issue (the Update App Intake that started
    # the run, so the retry sees them) and never opens a new issue for them:
    # [{kind, flag, check, evidence, repro}]. `regression` is a failed check of behaviour that was live before the change; `dark` is a failed
    # check of the new change, which stays dark. Only `failed` is a bug: a check that was blocked or not run was not seen to fail. The tester
    # only notes them; it files nothing, and nothing is taken out of git because of them.
    out = []
    for r in failures:
        if isinstance(r, dict) and check_state(r) == "failed":
            out.append({"kind": "regression" if r.get("scope") == "existing" else "dark", "flag": str(r.get("flag") or ""),
                        "check": " ".join(str(r.get("check") or "").split())[:200], "evidence": " ".join(str(r.get("evidence") or "").split())[:600],
                        "repro": " ".join(str(r.get("repro") or "").split())[:300]})
    return out[:MAX_BUGS]


def verification_record(doc, expected_flags):
    # What was verified, as a compact record for the Report and Summary: a count per state, each
    # check's state, and the limitations the tester reported (what it could not test or clean up).
    results = [r for r in (doc.get("results") if isinstance(doc, dict) else None) or [] if isinstance(r, dict)]
    counts = {state: 0 for state in track_progress.CHECK_STATES}
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


class VerifyDeployedApp:
    def test_deployed(self, base, head, rnd, flags):
        # The tester drives the deployed app (dark behind its flag, via the Preview Token; a first build without flags is tested against
        # the Intake) and says what a failure means: `regression`, `dark_only` or `ok` (`test_impact`). It has its own HOME for OpenHands
        # and its own checkout of `head`. Returns (passed, failures, impact).
        tester_tree = self.work / f"tester-tree-{rnd}"
        changed_files = self.git("diff", "--name-only", base, head, check=False).stdout.split()
        want_ui = bool(self.lim.get("ui_check", False)) and wants_ui_check(changed_files, getattr(self, "spec", None) or getattr(self, "task", ""))
        self.git("worktree", "add", "--detach", str(tester_tree), head)
        try:
            try:
                tdoc, cost, usage = self.agent_json(
                    "tester", f"t{rnd}", {"app_url": f"https://{self.app}.fly.dev", "head_sha": head,
                                          "report_path": self.work / f"test-report-{rnd}.json",
                                          "previous_report": track_progress.previous_report(self.work, rnd), "api_check": getattr(self, "api_check_path", API_CHECK),
                                          "ui_section": ui_section(want_ui, getattr(self, "ui_check_path", UI_CHECK)),
                                          "new_flags": ", ".join(f"`{f}`" for f in flags) or "none (no flag: check the spec's requirements)"},
                    self.work / f"test-report-{rnd}.json",
                    {"PREVIEW_TOKEN": self.preview, "API_CHECK_BASE": f"https://{self.app}.fly.dev",
                     "API_CHECK_LOG": str(self.work / f"api-check-{rnd}.jsonl"), "UI_CHECK_BASE": f"https://{self.app}.fly.dev",
                     "UI_CHECK_LOG": str(self.work / f"ui-check-{rnd}.jsonl"), "UI_CHECK_DIR": str(self.work),
                     **({"PLAYWRIGHT_BROWSERS_PATH": os.environ["PLAYWRIGHT_BROWSERS_PATH"]} if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else {})},
                    check=lambda doc: derive_test(doc, flags) and None,
                    cwd=tester_tree, home=self.work / f"home-tester-{rnd}")
            except run_stops.NeedsHuman:
                # No usable report, but if a helper saw something fail that is a finding the coder can act on: use it
                # instead of stopping for a person. With nothing failed there is nothing to act on, so it stops as before.
                tdoc = report_from_helper_failures(load_api_results(self.work / f"api-check-{rnd}.jsonl"),
                                                   load_api_results(self.work / f"ui-check-{rnd}.jsonl"))
                if tdoc is None:
                    raise
                log("The tester wrote no usable report; using what its helpers saw fail instead.")
                cost, usage = 0.0, None
        finally:
            self.git("worktree", "remove", "--force", str(tester_tree), check=False)
        tdoc = reconcile_api_checks(tdoc, load_api_results(self.work / f"api-check-{rnd}.jsonl"))
        tdoc = reconcile_ui_checks(tdoc, load_api_results(self.work / f"ui-check-{rnd}.jsonl"))
        try:  # so the next round's tester sees the failures the helper added; best effort, never a reason to stop the run
            (self.work / f"test-report-{rnd}.json").write_text(json.dumps(tdoc, indent=2))
        except OSError as e:
            log(f"could not rewrite the reconciled test report: {e}")
        passed, failures = derive_test(tdoc, flags)
        impact = test_impact(failures)
        self.state.d["bugs"] = bugs_from(failures)  # this pass's failures: a bug fixed by the next round is no longer a bug
        self.note_improvements(tdoc, "tester")
        self.state.d["verification"] = {"round": rnd, "sha": head, **verification_record(tdoc, flags)}
        self.state.stage("Test", "tester", rnd, cost, "passed" if passed else f"{len(failures)} failed ({impact})", usage)
        return passed, failures, impact
