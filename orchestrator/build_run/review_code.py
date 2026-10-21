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
    if f.get("category") not in BLOCKING_CATEGORIES:
        return f"category `{f.get('category')}` cannot block"
    kind = f.get("evidence_kind")
    if kind == "repro" and str(f.get("repro") or "").strip():
        return None
    if kind == "cited" and str(f.get("file") or "").strip() and str(f.get("line") or "").strip():
        return None
    return f"evidence `{kind}` is not backed by a {'repro' if kind == 'repro' else 'file and line'}"


def banded_findings(doc):
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
    findings = banded_findings(doc)
    blocking = [f for f in findings if f.get("severity") == "blocking"]
    minor = [f for f in findings if f.get("severity") != "blocking"]
    return not blocking, blocking, minor


def finding_view(source, summary, evidence, raw):
    out = {"source": source, "summary": summary, "evidence": evidence}
    out.update({k: raw[k] for k in DETAIL_FIELDS if str(raw.get(k) or "").strip()})
    return out


def describe_finding(f):
    where = f"{f['file']}:{f['line']}" if f.get("file") and f.get("line") else f.get("file") or ""
    rows = [("Where", where), ("Evidence", f.get("evidence")), ("Requirement", f.get("requirement")),
            ("Suggested fix", f.get("suggested_fix")), ("Repro", f.get("repro"))]
    body = "".join(f"\n    {k}: {v}" for k, v in rows if v)
    return f"- [{f['source']}] {f['summary']}{body}"


REVIEW_CONTEXT_FILES = ("backend/src/app.ts", "backend/src/feature-flags.ts")


SKIP_SUFFIXES = (".lock", "-lock.json", ".png", ".jpg", ".svg", ".ico", ".woff", ".woff2", ".map")


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


def flag_finding(summary, entry, requirement, fix):
    return {"severity": "minor", "category": "flag_misuse", "evidence_kind": "cited", "summary": summary, "evidence": entry,
            "file": "flags.json", "line": "", "requirement": requirement, "suggested_fix": fix, "repro": "", "source": "orchestrator"}


def declared_flags(git, head):
    try:
        return {f["slug"]: f for f in json.loads(git("show", f"{head}:flags.json") or "[]") if isinstance(f, dict) and "slug" in f}
    except ValueError:
        return None


def single_flag_findings(git, head, slug, entry):
    shown, out = json.dumps(entry), []
    if not flag_usage.code_reads(git, head, slug):
        out.append(flag_finding(f"Flag `{slug}` is declared in flags.json but no code outside the tests reads it", shown,
                                "A declared flag must guard something, or it is released with nothing behind it.",
                                "Check the flag with isFeatureEnabled(res, slug) at the change's entry point, or remove the entry."))
    if not FLAG_REF_RE.match(str(entry.get("description") or "")):
        out.append(flag_finding(f"Flag `{slug}` has no issue reference at the start of its description", shown,
                                "A flag's description starts with the story it came from (`owner/repo#number:`).",
                                "Start the description with the issue reference."))
    return out


def flag_findings(git, head, slugs):
    declared = declared_flags(git, head)
    if declared is None:
        return []
    return [f for slug in slugs if declared.get(slug) is not None for f in single_flag_findings(git, head, slug, declared[slug])]


SUPPRESSION_RE = re.compile(r"eslint-disable|@ts-ignore|@ts-nocheck")


def suppression_findings(git, base, head):
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
    pass


class FastReviewFailed(Exception):
    pass


def numbered(text):
    return "\n".join(f"{i}: {line}" for i, line in enumerate(text.split("\n"), 1))


def build_review_context(git, base, head, max_chars, spec=None):
    changed = [c for c in git("diff", "--name-only", "--diff-filter=d", base, head).split("\n") if c]
    shown = [c for c in changed if not c.endswith(SKIP_SUFFIXES)]
    extra = [f for f in REVIEW_CONTEXT_FILES if f not in shown]
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


def review_request_body(model, system, user):
    return {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "review_verdict", "schema": REVIEW_SCHEMA, "strict": True}}}


def reply_to_verdict(r):
    try:
        doc = json.loads(r["choices"][0]["message"]["content"])
        derive_review(doc)
        return doc, r.get("usage") or {}, None
    except (KeyError, IndexError, TypeError, ValueError) as e:
        return None, None, f"unusable reply: {e}"


def worth_retrying(status):
    return status in (0, 429) or status >= 500 or status == 200


def single_call_review(base_url, key, model, system, user, timeout=300, attempts=4):
    body = review_request_body(model, system, user)
    last = None
    for attempt in range(1, attempts + 1):
        status, r = http_client.request("POST", f"{base_url}/chat/completions", key, body, timeout=timeout)
        if status == 402:
            raise run_stops.ProviderBlocked(provider.BLOCKED_MESSAGE)
        doc, usage, last = reply_to_verdict(r) if status == 200 and isinstance(r, dict) else (None, None, f"HTTP {status}: {str(r)[:200]}")
        if doc is not None:
            return doc, usage
        if attempt == attempts or not worth_retrying(status):
            break
        time.sleep(5 * attempt)
    raise FastReviewFailed(last)


class ReviewCode:
    def fast_review(self, base, head, rnd):
        self.check_limits()
        role = self.cfg["roles"]["reviewer"]
        context = build_review_context(lambda *a: self.git(*a, check=False).stdout, base, head,
                                       self.lim.get("review_context_max_chars", 200000),
                                       spec=self.spec)
        system = prompts.render(prompts.load_prompt(role["fast_prompt"]), {"app_name": self.app, "base_sha": base[:8], "head_sha": head[:8]})
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
        base_flags = self.git("show", f"{base}:flags.json", check=False).stdout
        head_flags = self.git("show", f"{head}:flags.json", check=False).stdout
        flags = flag_manifest.new_flag_slugs(base_flags, head_flags)
        flags += [s for s in self.story_flags if s in flag_manifest.manifest_slugs(head_flags) and s not in flags]
        self.state.d["flags"] = list(flags)
        return flags

    def note_improvements(self, doc, source):
        self.state.d["improvements"] = suggestions.merge_improvements(self.state.d.get("improvements") or [], suggestions.improvements_from(doc, source))

    def single_call_or_none(self, base, head, rnd):
        if self.cfg["roles"]["reviewer"].get("mode", "agent") != "single_call":
            return None
        try:
            return self.fast_review(base, head, rnd)
        except (ContextTooLarge, FastReviewFailed) as e:
            log(f"Single-call review not possible ({e}); using the exploring reviewer.")
            return None

    def exploring_review(self, base, head, rnd):
        values = {"base_sha": base, "head_sha": head, "verdict_path": self.work / f"verdict-{rnd}.json"}
        return self.agent_json("reviewer", f"r{rnd}", values, self.work / f"verdict-{rnd}.json", check=lambda d: derive_review(d) and None,
                               home=self.work / f"home-reviewer-{rnd}")

    def review_before_push(self, base, head, rnd):
        self.state.d["review_passes"] = rnd
        self.restore_tree()
        doc, cost, usage = self.single_call_or_none(base, head, rnd) or self.exploring_review(base, head, rnd)
        self.restore_tree()
        clean, blocking, minor = derive_review(doc)
        git = lambda *a: self.git(*a, check=False).stdout
        minor = minor + flag_findings(git, head, self.run_flags(base, head)) + suppression_findings(git, base, head)
        self.note_improvements(doc, "reviewer")
        self.state.stage("Review", "reviewer", rnd, cost, "clean" if clean else f"{len(blocking)} blocking", usage)
        return clean, blocking, minor
