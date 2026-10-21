import json
import sys

from shared import outcomes

COST_OVERSHOOT_USD = 0.50


def _stages(d, name):
    return [s for s in d.get("stages", []) if s.get("stage") == name]


def broken(rule, detail):
    return [{"rule": rule, "detail": detail}]


def last_verdict(stages):
    return stages[-1].get("verdict") if stages else "none"


def release_was_recorded(d):
    return bool((d.get("release") or {}).get("released")) or d.get("outcome") == "released"


def unrecorded_outcome(d):
    return broken("A-01 a run records its outcome", "the Report still says `running`") if d.get("outcome") == "running" else []


def overspend(d, overshoot):
    cap, spent = d.get("cap_usd"), d.get("spent_usd") or 0
    if cap and spent > cap + overshoot:
        return broken("INV-09 spend stays within the cap", f"${spent:.2f} spent against a ${cap:.2f} cap (allowed overshoot ${overshoot:.2f})")
    return []


def release_gate_problems(d):
    reviews, tests = _stages(d, "Review"), _stages(d, "Test")
    problems = []
    if last_verdict(reviews) != "clean":
        problems += broken("INV-03 release needs a clean review", f"last Review stage: {last_verdict(reviews)}")
    if last_verdict(tests) != "passed":
        problems += broken("INV-03 release needs a passing test", f"last Test stage: {last_verdict(tests)}")
    if reviews and tests and reviews[-1].get("round") != tests[-1].get("round"):
        problems += broken("INV-03 release needs one reviewed and tested SHA", f"last review round {reviews[-1].get('round')}, last test round {tests[-1].get('round')}")
    return problems


def release_evidence_problems(d):
    problems = [] if d.get("head_sha") else broken("INV-03 release is for a known SHA", "no head_sha recorded")
    ver = d.get("verification")
    if ver and any(ver["counts"].get(k) for k in ("failed", "blocked", "not_run")):
        problems += broken("INV-05 only passed checks release", f"verification counts at release: {ver['counts']}")
    return problems


def release_before_last_review(d):
    names = [s.get("stage") for s in d.get("stages", [])]
    if "Release" not in names:
        return False
    return "Review" not in names or names.index("Release") < max(i for i, n in enumerate(names) if n == "Review")


def release_problems(d):
    if not release_was_recorded(d):
        return []
    problems = release_gate_problems(d) + release_evidence_problems(d)
    if release_before_last_review(d):
        problems += broken("A-03 stage order", "the Release stage ran before the last Review stage")
    return problems


def watchdog_problems(d):
    if d.get("outcome") == "watchdog_disabled" and not (d.get("release") or {}).get("released"):
        return broken("INV-07 the watchdog acts on this run's release", "watchdog_disabled with nothing released")
    return []


def open_findings_problems(d):
    if d.get("outcome") in outcomes.OK and d.get("blocking"):
        return broken("A-04 a finished run has no open blocking findings", f"{len(d['blocking'])} still open at the end")
    return []


def empty_update_problems(d):
    if d.get("outcome") in outcomes.OK and d.get("build_kind") == "update" and not (d.get("commits") or []):
        return broken("A-05 an update changes something", "an update finished OK with no coder commit")
    return []


def rollback_problems(d):
    if d.get("outcome") != "regression" or not d.get("commits"):
        return []
    rb = d.get("rollback")
    if rb is None:
        return broken("A-07 a regression rolls the deploy back", "the tester found a regression, but no rollback was attempted or recorded")
    if rb.get("status") == "failed":
        return broken("A-07 a regression rolls the deploy back", f"the rollback failed ({rb.get('reason')}); the live app is still on the regressing version")
    return []


def revert_problems(d):
    if d.get("revert"):
        return broken("A-08 nothing is reverted in git", "the Report records a git revert; code is fixed forward and only the deploy is rolled back")
    return []


def audit_report(d, overshoot=COST_OVERSHOOT_USD):
    groups = (unrecorded_outcome(d), overspend(d, overshoot), release_problems(d), watchdog_problems(d), open_findings_problems(d),
              empty_update_problems(d), rollback_problems(d), revert_problems(d))
    return [problem for group in groups for problem in group]


def render_audit(problems):
    if not problems:
        return ""
    lines = ["", f"**Audit: {len(problems)} invariant(s) broken in this run**", ""]
    return "\n".join(lines + [f"- {p['rule']}: {p['detail']}" for p in problems]) + "\n"


def main(argv):
    with open(argv[1], encoding="utf-8") as f:
        problems = audit_report(json.load(f))
    print(render_audit(problems) or "audit: no invariant broken")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
