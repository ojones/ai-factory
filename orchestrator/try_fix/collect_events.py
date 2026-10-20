# STEP 6.2: the failure events of one Build Run, from its facts (retrospective/run_facts.py). The run's own ending is the one `failure`; the
# warnings are the things that did not stop the run but are worth a look (a dark-only test failure, a check that could not be run, a minor finding,
# an improvement for the app, a flag that was missing). The Retrospective gives each event a verdict; nothing here decides to fix anything.
from shared import outcomes

from try_fix import event

MAX_WARNINGS = 8


def run_failure(d):
    # The outcome that is a failure to fix: not a good ending, not an answer (refused, awaiting_secret) and not the provider running out of balance.
    return d.get("outcome") not in outcomes.OK + outcomes.ANSWERED + (outcomes.PROVIDER_BLOCKED,)


def from_run(facts, fingerprint):
    app, story, flags = facts.get("app"), facts.get("issue_number"), facts.get("flags") or []
    flag = flags[0] if flags else None
    ended_well = facts.get("outcome") in outcomes.OK
    released = True if ended_well and flag else (False if flag else None)
    found = []
    if run_failure(facts):
        source = "watchdog" if facts.get("outcome") == outcomes.WATCHDOG_DISABLED else "build_run"
        found.append(event.make(source, "failure", app, facts.get("message") or facts.get("outcome"), fingerprint,
                                evidence=facts.get("run_url"), story=story, flag=flag, released=False if source == "watchdog" else released))
    if ended_well:
        for b in facts.get("bugs") or []:
            found.append(event.make("tester", "warning", app, f"{b.get('kind')}: {b.get('check')}", [b.get("kind"), b.get("check")],
                                    evidence=b.get("evidence"), story=story, flag=b.get("flag") or flag, released=released))
    for u in facts.get("unverified") or []:
        found.append(event.make("tester", "warning", app, f"a check could not be verified ({u.get('state')}): {u.get('check')}",
                                ["unverified", u.get("check")], story=story, flag=flag, released=released))
    for m in facts.get("final_minor") or []:
        found.append(event.make("reviewer", "warning", app, m.get("summary"), ["minor", m.get("summary")], evidence=m.get("evidence"),
                                story=story, flag=flag, released=released))
    for i in facts.get("improvements") or []:
        if i.get("target") == "managed_app":
            found.append(event.make(i.get("source") if i.get("source") in ("reviewer", "tester") else "reviewer", "warning", app, i.get("summary"),
                                    ["improvement", i.get("summary")], evidence=i.get("evidence"), story=story, flag=flag, released=released))
    for n in facts.get("flag_notes") or []:
        found.append(event.make("build_run", "warning", app, f"flag {n.get('slug')}: {n.get('kind')}", ["flag", n.get("kind"), n.get("slug")],
                                evidence=n.get("guess"), story=story, flag=n.get("slug") or flag, released=released))
    failures = [e for e in found if e["severity"] == "failure"]
    warnings = [e for e in found if e["severity"] == "warning"][:MAX_WARNINGS]
    return failures + warnings
