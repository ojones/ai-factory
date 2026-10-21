from shared import outcomes

from try_fix import event

MAX_WARNINGS = 8


def run_failure(d):
    return d.get("outcome") not in outcomes.OK + outcomes.ANSWERED + (outcomes.PROVIDER_BLOCKED,)


class RunContext:
    def __init__(self, facts, fingerprint):
        self.facts, self.fingerprint = facts, fingerprint
        self.app, self.story = facts.get("app"), facts.get("issue_number")
        flags = facts.get("flags") or []
        self.flag = flags[0] if flags else None
        self.ended_well = facts.get("outcome") in outcomes.OK
        self.released = True if self.ended_well and self.flag else (False if self.flag else None)

    def warning(self, source, summary, key, evidence=None, flag=None):
        return event.make(source, "warning", self.app, summary, key, evidence=evidence, story=self.story, flag=flag or self.flag, released=self.released)


def failure_events(ctx):
    if not run_failure(ctx.facts):
        return []
    facts = ctx.facts
    source = "watchdog" if facts.get("outcome") == outcomes.WATCHDOG_DISABLED else "build_run"
    return [event.make(source, "failure", ctx.app, facts.get("message") or facts.get("outcome"), ctx.fingerprint, evidence=facts.get("run_url"),
                       story=ctx.story, flag=ctx.flag, released=False if source == "watchdog" else ctx.released)]


def bug_events(ctx):
    bugs = ctx.facts.get("bugs") or [] if ctx.ended_well else []
    return [ctx.warning("tester", f"{b.get('kind')}: {b.get('check')}", [b.get("kind"), b.get("check")], b.get("evidence"), b.get("flag")) for b in bugs]


def unverified_events(ctx):
    return [ctx.warning("tester", f"a check could not be verified ({u.get('state')}): {u.get('check')}", ["unverified", u.get("check")])
            for u in ctx.facts.get("unverified") or []]


def minor_events(ctx):
    return [ctx.warning("reviewer", m.get("summary"), ["minor", m.get("summary")], m.get("evidence")) for m in ctx.facts.get("final_minor") or []]


def improvement_events(ctx):
    mine = [i for i in ctx.facts.get("improvements") or [] if i.get("target") == "managed_app"]
    return [ctx.warning(i.get("source") if i.get("source") in ("reviewer", "tester") else "reviewer", i.get("summary"), ["improvement", i.get("summary")], i.get("evidence"))
            for i in mine]


def flag_note_events(ctx):
    return [ctx.warning("build_run", f"flag {n.get('slug')}: {n.get('kind')}", ["flag", n.get("kind"), n.get("slug")], n.get("guess"), n.get("slug"))
            for n in ctx.facts.get("flag_notes") or []]


def from_run(facts, fingerprint):
    ctx = RunContext(facts, fingerprint)
    found = failure_events(ctx)
    for collect in (bug_events, unverified_events, minor_events, improvement_events, flag_note_events):
        found += collect(ctx)
    failures = [e for e in found if e["severity"] == "failure"]
    warnings = [e for e in found if e["severity"] == "warning"][:MAX_WARNINGS]
    return failures + warnings

