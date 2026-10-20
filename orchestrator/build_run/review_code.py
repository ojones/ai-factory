# STEP 4.5: the single-call review of the local commit before anything is pushed: the context it is given, banded findings, the verdict, flag and
# suppression findings.
import json
import re
import time

from flag_lifecycle import (
    flag_manifest,
    flag_usage,
)
from shared import (
    http_client,
    prompts,
    provider,
    run_stops,
)
from shared.console import log

from build_run import suggestions

FINDING_CATEGORIES = ("correctness", "security", "data_safety", "requirement_not_met", "flag_misuse", "test_quality", "style", "duplication", "other")


BLOCKING_CATEGORIES = ("correctness", "security", "data_safety", "requirement_not_met", "flag_misuse", "test_quality")


EVIDENCE_KINDS = ("repro", "cited", "opinion")


def finding_support(f):
    # Why a finding the reviewer called blocking cannot block, or None when its fields support it. It blocks only if its category is one
    # that can (not style, duplication or other) and its evidence is something to act on: a `repro` (a command or check that shows it) or
    # a citation (a file and line). An opinion never blocks.
    if f.get("category") not in BLOCKING_CATEGORIES:
        return f"category `{f.get('category')}` cannot block"
    kind = f.get("evidence_kind")
    if kind == "repro" and str(f.get("repro") or "").strip():
        return None
    if kind == "cited" and str(f.get("file") or "").strip() and str(f.get("line") or "").strip():
        return None
    return f"evidence `{kind}` is not backed by a {'repro' if kind == 'repro' else 'file and line'}"


def banded_findings(doc):
    # The reviewer's findings with each one's band decided from its structured fields, never from the model's label alone. A finding
    # the reviewer called blocking keeps that only if `finding_support` finds the fields back it; otherwise it is minor, with the reason in
    # `downgraded`. A minor finding is never raised. A document whose findings lack the structure raises ValueError, so the caller asks again
    # instead of trusting a label (the same way a missing findings list is handled).
    findings = doc.get("findings") if isinstance(doc, dict) else None
    if not isinstance(findings, list):
        raise ValueError("reviewer output has no findings list")
    out = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        if f.get("category") not in FINDING_CATEGORIES or f.get("evidence_kind") not in EVIDENCE_KINDS:
            raise ValueError(f"a reviewer finding has no valid category and evidence_kind: {str(f.get('summary'))[:80]!r}")
        why = finding_support(f) if f.get("severity") == "blocking" else None
        out.append(dict(f, severity="minor", downgraded=why) if why else dict(f))
    return out


def derive_review(doc):
    # (clean, blocking, minor). The verdict comes from the findings and their structure, never the model's own field.
    findings = banded_findings(doc)
    blocking = [f for f in findings if f.get("severity") == "blocking"]
    minor = [f for f in findings if f.get("severity") != "blocking"]
    return not blocking, blocking, minor


def finding_view(source, summary, evidence, raw):
    # A finding as handed to the coder: summary, evidence, and any of the detail fields present.
    out = {"source": source, "summary": summary, "evidence": evidence}
    out.update({k: raw[k] for k in DETAIL_FIELDS if str(raw.get(k) or "").strip()})
    return out


def describe_finding(f):
    # One finding as an indented block for the coder's fix list.
    where = f"{f['file']}:{f['line']}" if f.get("file") and f.get("line") else f.get("file") or ""
    rows = [("Where", where), ("Evidence", f.get("evidence")), ("Requirement", f.get("requirement")),
            ("Suggested fix", f.get("suggested_fix")), ("Repro", f.get("repro"))]
    body = "".join(f"\n    {k}: {v}" for k, v in rows if v)
    return f"- [{f['source']}] {f['summary']}{body}"


# The two files every route passes through: the reviewer must see them even when unchanged,
# to judge kill-switch ordering and how flags fail closed.
REVIEW_CONTEXT_FILES = ("backend/src/app.ts", "backend/src/feature-flags.ts")


SKIP_SUFFIXES = (".lock", "-lock.json", ".png", ".jpg", ".svg", ".ico", ".woff", ".woff2", ".map")


# Detail a finding may carry so the coder can act without exploring; all best-effort, "" when not applicable.
DETAIL_FIELDS = ("file", "line", "requirement", "suggested_fix", "repro", "category")


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {"severity": {"type": "string", "enum": ["blocking", "minor"]},
                           "category": {"type": "string", "enum": list(FINDING_CATEGORIES)},
                           "evidence_kind": {"type": "string", "enum": list(EVIDENCE_KINDS)},
                           "summary": {"type": "string"}, "evidence": {"type": "string"},
                           **{k: {"type": "string"} for k in DETAIL_FIELDS}},
            "required": ["severity", "category", "evidence_kind", "summary", "evidence", *DETAIL_FIELDS], "additionalProperties": False}},
        "improvements": {"type": "array", "items": {
            "type": "object",
            "properties": {"target": {"type": "string", "enum": list(suggestions.IMPROVEMENT_TARGETS)},
                           "summary": {"type": "string"}, "evidence": {"type": "string"}},
            "required": ["target", "summary", "evidence"], "additionalProperties": False}},
        "verdict": {"type": "string", "enum": ["clean", "changes_requested"]},
    },
    "required": ["analysis", "findings", "improvements", "verdict"],
    "additionalProperties": False,
}


FLAG_REF_RE = re.compile(r"^[\w.-]+/[\w.-]+#\d+:")


def flag_findings(git, head, slugs):
    # Findings about this change's own flags that need no judgement, so the reviewer is not asked for them and the severity is fixed:
    # a flag in `flags.json` that no code outside the tests reads (it would be released with nothing behind it), and a flag whose
    # description does not start with an issue reference (it must point back to its story). Both are minor. `git(*args)` returns a git
    # command's stdout ('' when it fails), run in the app checkout.
    try:
        declared = {f["slug"]: f for f in json.loads(git("show", f"{head}:flags.json") or "[]") if isinstance(f, dict) and "slug" in f}
    except ValueError:
        return []
    out = []

    def finding(slug, summary, entry, requirement, fix):
        return {"severity": "minor", "category": "flag_misuse", "evidence_kind": "cited", "summary": summary, "evidence": entry,
                "file": "flags.json", "line": "", "requirement": requirement, "suggested_fix": fix, "repro": "", "source": "orchestrator"}
    for slug in slugs:
        entry = declared.get(slug)
        if entry is None:
            continue
        shown = json.dumps(entry)
        hits = flag_usage.code_reads(git, head, slug)
        if not hits:
            out.append(finding(slug, f"Flag `{slug}` is declared in flags.json but no code outside the tests reads it", shown,
                               "A declared flag must guard something, or it is released with nothing behind it.",
                               "Check the flag with isFeatureEnabled(res, slug) at the change's entry point, or remove the entry."))
        if not FLAG_REF_RE.match(str(entry.get("description") or "")):
            out.append(finding(slug, f"Flag `{slug}` has no issue reference at the start of its description", shown,
                               "A flag's description starts with the story it came from (`owner/repo#number:`).",
                               "Start the description with the issue reference."))
    return out


SUPPRESSION_RE = re.compile(r"eslint-disable|@ts-ignore|@ts-nocheck")


def suppression_findings(git, base, head):
    # A minor finding when the change adds a lint or type-check suppression (`eslint-disable`, `@ts-ignore`, `@ts-nocheck`). The lint config
    # is the Orchestrator's, so the coder cannot loosen a rule for the whole app; a suppression is the local way around one, so it is named
    # where the retrospective sees it and can ask for a better rule or default. Always minor: one is sometimes right. `git(*args)` returns a
    # git command's stdout ('' when it fails), run in the app checkout.
    hits, path, line = [], "", 0
    for text in git("diff", "-U0", base, head, "--", "*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs").splitlines():
        if text.startswith("+++ b/"):
            path = text[6:]
        elif text.startswith("@@"):
            m = re.search(r"\+(\d+)", text)
            line = int(m.group(1)) - 1 if m else 0
        elif text.startswith("+"):
            line += 1
            if SUPPRESSION_RE.search(text):
                hits.append(f"{path}:{line}: {text[1:].strip()[:100]}")
    if not hits:
        return []
    first = hits[0].split(":")
    return [{"severity": "minor", "category": "style", "evidence_kind": "cited",
             "summary": f"The change adds {len(hits)} lint or type-check suppression(s)", "evidence": "; ".join(hits[:3]),
             "file": first[0], "line": first[1], "requirement": "Fix the code the rule reports; the lint config is not the coder's to loosen.",
             "suggested_fix": "Remove the suppression and satisfy the rule.", "repro": "", "source": "orchestrator"}]


class ContextTooLarge(Exception):
    # The change does not fit in one prompt; the caller falls back to the exploring Agent.
    pass


class FastReviewFailed(Exception):
    # The single call produced nothing usable; the caller falls back to the exploring Agent.
    pass


def numbered(text):
    return "\n".join(f"{i}: {line}" for i, line in enumerate(text.split("\n"), 1))


def build_review_context(git, base, head, max_chars, spec=None):
    # Everything the reviewer would otherwise go and look up, in one message.
    #
    # `git(*args)` returns a git command's stdout ('' when it fails), run in the app checkout.
    # Raises ContextTooLarge when the change cannot be shown whole, so a partial view never
    # stands in for a review.
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
    # One structured chat completion. Retries overload and server errors; returns (document, usage).
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "review_verdict", "schema": REVIEW_SCHEMA, "strict": True}}}
    last = None
    for attempt in range(1, attempts + 1):
        status, r = http_client.request("POST", f"{base_url}/chat/completions", key, body, timeout=timeout)
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
                raise run_stops.ProviderBlocked(provider.BLOCKED_MESSAGE)
        if attempt < attempts and (status in (0, 429) or status >= 500 or status == 200):
            time.sleep(5 * attempt)
        else:
            break
    raise FastReviewFailed(last)


class ReviewCode:
    def fast_review(self, base, head, rnd):
        # The reviewer as one model call over a prompt the Orchestrator assembles (no tools, no
        # exploring). Returns (document, cost, usage) like agent_json, or raises ContextTooLarge or
        # FastReviewFailed, in which case the caller uses the exploring Agent.
        self.check_limits()
        role = self.cfg["roles"]["reviewer"]
        context = build_review_context(lambda *a: self.git(*a, check=False).stdout, base, head,
                                       self.lim.get("review_context_max_chars", 200000),
                                       spec=self.spec if getattr(self, "update_intake", False) else None)
        system = prompts.render(prompts.load_prompt(role["fast_prompt"]), {"app_name": self.app, "build_kind": self.build_kind, "base_sha": base[:8], "head_sha": head[:8]})
        jwt = self.meter.mint(role["model"])
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
        log(f"reviewer (r{rnd}) single call: {time.time() - start:.0f}s, {prompt_tokens:,} prompt and "
            f"{usage['completion_tokens']:,} output tokens, cost ${cost:.4f}")
        return doc, cost, usage

    def run_flags(self, base, head):
        # The flags this change releases: new in `flags.json`, plus a retried story's own flag, which is already in the manifest (the failed
        # attempt's code stayed, dark) but is tested and released again like a new one.
        base_flags = self.git("show", f"{base}:flags.json", check=False).stdout
        head_flags = self.git("show", f"{head}:flags.json", check=False).stdout
        flags = flag_manifest.new_flag_slugs(base_flags, head_flags)
        flags += [s for s in self.reuse_flags if s in flag_manifest.manifest_slugs(head_flags) and s not in flags]
        self.state.d["flags"] = list(flags)
        return flags

    def note_improvements(self, doc, source):
        # Keep the improvements an Agent suggested for the Report; the retrospective files them.
        self.state.d["improvements"] = suggestions.merge_improvements(self.state.d.get("improvements") or [], suggestions.improvements_from(doc, source))

    def review_before_push(self, base, head, rnd):
        # The reviewer reads the local commit before anything is pushed or deployed, so code it blocks never reaches `main`. A single
        # model call over a prompt the Orchestrator assembles, or the exploring Agent when the change is too big or the call fails.
        # Returns (clean, blocking findings, minor findings).
        self.state.d["review_passes"] = rnd
        self.restore_tree()
        role_mode = self.cfg["roles"]["reviewer"].get("mode", "agent")
        doc = None
        if role_mode == "single_call":
            try:
                doc, cost, usage = self.fast_review(base, head, rnd)
            except (ContextTooLarge, FastReviewFailed) as e:
                log(f"Single-call review not possible ({e}); using the exploring reviewer.")
        if doc is None:
            doc, cost, usage = self.agent_json(
                "reviewer", f"r{rnd}", {"base_sha": base, "head_sha": head, "verdict_path": self.work / f"verdict-{rnd}.json"},
                self.work / f"verdict-{rnd}.json", check=lambda d: derive_review(d) and None,
                home=self.work / f"home-reviewer-{rnd}")
        self.restore_tree()
        clean, blocking, minor = derive_review(doc)
        git = lambda *a: self.git(*a, check=False).stdout
        minor = minor + flag_findings(git, head, self.run_flags(base, head)) + suppression_findings(git, base, head)
        self.note_improvements(doc, "reviewer")
        self.state.stage("Review", "reviewer", rnd, cost, "clean" if clean else f"{len(blocking)} blocking", usage)
        return clean, blocking, minor
