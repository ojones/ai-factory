import json
import os
import re
from pathlib import Path

from shared import (
    config,
    run_stops,
)
from shared.console import log

from build_run import track_progress

API_CHECK = str(config.FACTORY_DIR / "orchestrator" / "shared" / "api_check.py")


UI_CHECK = str(config.FACTORY_DIR / "orchestrator" / "build_run" / "ui_check.py")


UNOBSERVED_RE = re.compile(
    r"\b(unable to|not able to|cannot|can't|could not|couldn't|did not|didn't|no way to|no access to)\s+(directly\s+)?"
    r"(observe|verify|see|view|read|check|confirm|access|inspect|determine|validate)\b|\bunverifi(able|ed)\b|\bnot (been )?(verified|observed)\b", re.I)


RAN_A_TEST_RE = re.compile(r"\b(npm (run )?test|vitest|jest|unit test|test file|test suite|tests? (pass|passed|asserts?))\b", re.I)


def admits_unobserved(evidence):
    text = str(evidence or "")
    return bool(UNOBSERVED_RE.search(text)) and not RAN_A_TEST_RE.search(text)


def check_state(r):
    if not isinstance(r, dict):
        return "failed"
    state = r["status"] if r.get("status") in track_progress.CHECK_STATES else ("passed" if r.get("passed") is True else "failed")
    if state == "passed" and admits_unobserved(r.get("evidence")):
        return "not_run"
    return state


def load_api_results(path):
    out = {}
    if not Path(path).is_file():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            out[r["id"]] = r
    return out


def _helper_ids(result, field):
    ids = result.get(field)
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else ([ids] if isinstance(ids, str) else [])


def helper_failure_text(found, ids):
    return "; ".join(f"{i}: {'; '.join(found[i].get('problems') or ['failed'])}" for i in ids)


def append_evidence(r, note):
    return f"{r.get('evidence', '')} | {note}".strip(" |")


def reconcile_cited_result(r, found, field, label):
    ids = _helper_ids(r, field)
    failing = [i for i in ids if i in found and not found[i].get("ok")]
    unknown = [i for i in ids if i not in found]
    if check_state(r) != "passed":
        return
    if failing:
        r.update(status="failed", passed=False, evidence=append_evidence(r, f"the {label} helper observed otherwise: " + helper_failure_text(found, failing)))
    elif unknown:
        r.update(status="not_run", passed=False, evidence=append_evidence(r, f"cites {label} id(s) the helper never ran: " + ", ".join(unknown)))


def unreported_failure(res, i, flag, field, label):
    observed = res.get("observed") or {}
    seen = f" (status {observed.get('status')})" if "status" in observed else ""
    return {"flag": flag, "check": f"{label} {i}: {res.get('name', i)}", "status": "failed", "passed": False, field: [i],
            "evidence": f"the {label} helper observed a failure the report did not mention: " + "; ".join(res.get("problems") or ["failed"]) + seen}


def reconcile_helper_checks(doc, found, field, label):
    results = [dict(r) for r in (doc.get("results") if isinstance(doc, dict) else None) or [] if isinstance(r, dict)]
    cited = set()
    for r in results:
        cited.update(_helper_ids(r, field))
        reconcile_cited_result(r, found, field, label)
    flag = next((r.get("flag") for r in results if r.get("flag")), "")
    results += [unreported_failure(res, i, flag, field, label) for i, res in found.items() if not res.get("ok") and i not in cited]
    return {**doc, "results": results}


def report_from_helper_failures(api, ui):
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
    return any(str(f).startswith("frontend/") for f in changed_files) or bool(UI_WORDS.search(spec or ""))


def ui_section(wanted, helper_path):
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
    if not failures:
        return "ok"
    for r in failures:
        if isinstance(r, dict) and r.get("scope") == "existing" and check_state(r) == "failed" and (r.get("api") or r.get("ui")):
            return "regression"
    return "dark_only"


MAX_BUGS = 10


def failed_checks(failures):
    return [r for r in failures if isinstance(r, dict) and check_state(r) == "failed"]


def unverified_checks(failures):
    return [{"check": " ".join(str(r.get("check") or "?").split())[:200], "state": check_state(r)}
            for r in failures if isinstance(r, dict) and check_state(r) in ("blocked", "not_run")][:MAX_BUGS]


def unverified_message(failures):
    states = {}
    for r in failures:
        if isinstance(r, dict):
            states[check_state(r)] = states.get(check_state(r), 0) + 1
    names = "; ".join(str(r.get("check") or "?")[:80] for r in failures[:3] if isinstance(r, dict))
    return (f"{len(failures)} check(s) could not be verified ({', '.join(f'{n} {k}' for k, n in sorted(states.items()))}), and none failed, "
            f"so another coder round cannot help. Unverified: {names}")


def bugs_from(failures):
    out = []
    for r in failures:
        if isinstance(r, dict) and check_state(r) == "failed":
            out.append({"kind": "regression" if r.get("scope") == "existing" else "dark", "flag": str(r.get("flag") or ""),
                        "check": " ".join(str(r.get("check") or "").split())[:200], "evidence": " ".join(str(r.get("evidence") or "").split())[:600],
                        "repro": " ".join(str(r.get("repro") or "").split())[:300]})
    return out[:MAX_BUGS]


def verification_record(doc, expected_flags):
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
    def app_url(self):
        return f"https://{self.app}.fly.dev"

    def wants_ui(self, base, head):
        changed_files = self.git("diff", "--name-only", base, head, check=False).stdout.split()
        return bool(self.lim.get("ui_check", False)) and wants_ui_check(changed_files, getattr(self, "spec", None) or getattr(self, "task", ""))

    def tester_values(self, rnd, head, flags, want_ui):
        return {"app_url": self.app_url(), "head_sha": head, "report_path": self.work / f"test-report-{rnd}.json",
                "previous_report": track_progress.previous_report(self.work, rnd), "api_check": getattr(self, "api_check_path", API_CHECK),
                "ui_section": ui_section(want_ui, getattr(self, "ui_check_path", UI_CHECK)),
                "new_flags": ", ".join(f"`{f}`" for f in flags) or "none (no flag: check the spec's requirements)"}

    def tester_env(self, rnd):
        browsers = {"PLAYWRIGHT_BROWSERS_PATH": os.environ["PLAYWRIGHT_BROWSERS_PATH"]} if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else {}
        return {"PREVIEW_TOKEN": self.preview, "API_CHECK_BASE": self.app_url(), "API_CHECK_LOG": str(self.work / f"api-check-{rnd}.jsonl"),
                "UI_CHECK_BASE": self.app_url(), "UI_CHECK_LOG": str(self.work / f"ui-check-{rnd}.jsonl"), "UI_CHECK_DIR": str(self.work), **browsers}

    def ask_tester(self, rnd, head, flags, want_ui, tester_tree):
        return self.agent_json("tester", f"t{rnd}", self.tester_values(rnd, head, flags, want_ui), self.work / f"test-report-{rnd}.json", self.tester_env(rnd),
                               check=lambda doc: derive_test(doc, flags) and None, cwd=tester_tree, home=self.work / f"home-tester-{rnd}")

    def report_from_failed_helpers(self, rnd):
        tdoc = report_from_helper_failures(load_api_results(self.work / f"api-check-{rnd}.jsonl"), load_api_results(self.work / f"ui-check-{rnd}.jsonl"))
        if tdoc is not None:
            log("The tester wrote no usable report; using what its helpers saw fail instead.")
        return tdoc

    def tester_report(self, rnd, head, flags, want_ui):
        tester_tree = self.work / f"tester-tree-{rnd}"
        self.git("worktree", "add", "--detach", str(tester_tree), head)
        try:
            return self.ask_tester(rnd, head, flags, want_ui, tester_tree)
        except run_stops.NeedsHuman:
            tdoc = self.report_from_failed_helpers(rnd)
            if tdoc is None:
                raise
            return tdoc, 0.0, None
        finally:
            self.git("worktree", "remove", "--force", str(tester_tree), check=False)

    def reconciled_report(self, tdoc, rnd):
        tdoc = reconcile_api_checks(tdoc, load_api_results(self.work / f"api-check-{rnd}.jsonl"))
        tdoc = reconcile_ui_checks(tdoc, load_api_results(self.work / f"ui-check-{rnd}.jsonl"))
        try:
            (self.work / f"test-report-{rnd}.json").write_text(json.dumps(tdoc, indent=2))
        except OSError as e:
            log(f"could not rewrite the reconciled test report: {e}")
        return tdoc

    def test_deployed(self, base, head, rnd, flags):
        tdoc, cost, usage = self.tester_report(rnd, head, flags, self.wants_ui(base, head))
        tdoc = self.reconciled_report(tdoc, rnd)
        passed, failures = derive_test(tdoc, flags)
        impact = test_impact(failures)
        self.state.d["bugs"] = bugs_from(failures)
        self.note_improvements(tdoc, "tester")
        self.state.d["verification"] = {"round": rnd, "sha": head, **verification_record(tdoc, flags)}
        self.state.stage("Test", "tester", rnd, cost, "passed" if passed else f"{len(failures)} failed ({impact})", usage)
        return passed, failures, impact
