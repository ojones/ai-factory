"""Check a finished Build Run's Report against the design invariants (docs/invariants.md).

The unit tests prove the code does what the rules say; this checks that a real run did. It reads only the
Report (`state.json`, as `finalize` writes it) and returns the rules it finds broken, so a bug that only
shows up in production, or a run that went around the code, still leaves a record. `finalize` stores the
result in the Report (`audit`) and the Summary; the post-mortem turns a violation into a lesson.

Pure functions, no network. Usage: audit.py <build-run-report.json>   (exit 1 if anything is violated)
"""
import json
import sys

# One review-and-test pass is a Review stage and a Test stage with the same round number.
COST_OVERSHOOT_USD = 0.50  # the call that crosses the cap completes (ARCHITECTURE.md: Cost guardrails)
OK_OUTCOMES = ("released", "nothing_to_release", "planned")


def _stages(d, name):
    return [s for s in d.get("stages", []) if s.get("stage") == name]


def audit_report(d, overshoot=COST_OVERSHOOT_USD):
    """A list of {"rule", "detail"} for every invariant the run's Report contradicts; empty when none."""
    problems = []

    def bad(rule, detail):
        problems.append({"rule": rule, "detail": detail})

    outcome = d.get("outcome")
    if outcome == "running":
        bad("A-01 a run records its outcome", "the Report still says `running`")

    cap, spent = d.get("cap_usd"), d.get("spent_usd") or 0
    if cap and spent > cap + overshoot:
        bad("INV-09 spend stays within the cap", f"${spent:.2f} spent against a ${cap:.2f} cap (allowed overshoot ${overshoot:.2f})")

    released = (d.get("release") or {}).get("released") or []
    if released or outcome == "released":
        reviews = _stages(d, "Review")
        tests = _stages(d, "Test")
        if not reviews or reviews[-1].get("verdict") != "clean":
            bad("INV-03 release needs a clean review", f"last Review stage: {reviews[-1].get('verdict') if reviews else 'none'}")
        if not tests or tests[-1].get("verdict") != "passed":
            bad("INV-03 release needs a passing test", f"last Test stage: {tests[-1].get('verdict') if tests else 'none'}")
        if reviews and tests and reviews[-1].get("round") != tests[-1].get("round"):
            bad("INV-03 release needs one reviewed and tested SHA", f"last review round {reviews[-1].get('round')}, last test round {tests[-1].get('round')}")
        if not d.get("head_sha"):
            bad("INV-03 release is for a known SHA", "no head_sha recorded")
        ver = d.get("verification")
        if ver and any(ver["counts"].get(k) for k in ("failed", "blocked", "not_run")):
            bad("INV-05 only passed checks release", f"verification counts at release: {ver['counts']}")
        names = [s.get("stage") for s in d.get("stages", [])]
        if "Release" in names and ("Review" not in names or names.index("Release") < max(i for i, n in enumerate(names) if n == "Review")):
            bad("A-03 stage order", "the Release stage ran before the last Review stage")

    if outcome == "watchdog_disabled" and not released:
        bad("INV-07 the watchdog acts on this run's release", "watchdog_disabled with nothing released")

    if outcome in OK_OUTCOMES and d.get("blocking"):
        bad("A-04 a finished run has no open blocking findings", f"{len(d['blocking'])} still open at the end")

    commits = d.get("commits") or []
    if outcome in OK_OUTCOMES and outcome != "planned" and d.get("build_kind") == "update" and not commits:
        bad("A-05 an update changes something", "an update finished OK with no coder commit")

    if outcome == "planned" and len(((d.get("plan") or {}).get("change_sets")) or []) < 2:
        bad("A-06 a planned run has a plan to hand on", "outcome `planned` without two or more change sets in the plan")

    return problems


def render_audit(problems):
    if not problems:
        return ""
    lines = ["", f"**Audit: {len(problems)} invariant(s) broken in this run**", ""]
    return "\n".join(lines + [f"- {p['rule']}: {p['detail']}" for p in problems]) + "\n"


def main(argv):
    with open(argv[1]) as f:
        problems = audit_report(json.load(f))
    print(render_audit(problems) or "audit: no invariant broken")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
