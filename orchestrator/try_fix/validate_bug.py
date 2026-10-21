import re

from planning import triage

MAX_SENTENCE = 600
MAX_ITEM = 300
MIN_REQUIREMENT = 15
MAX_TAKES = 4
VAGUE = re.compile(r"(?i)^\s*(consider|try to|maybe|perhaps|improve|better|enhance|ensure it works)\b|\b(as appropriate|where possible|if possible|etc\.?)\b")


REDACTED = "(secret value redacted)"


def scrub(text):
    for _, pattern in triage.SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text or "")
    return text


def clean(text, n):
    return " ".join(str(text or "").split())[:n]


def strings(value, n):
    return [clean(x, n) for x in value if isinstance(x, str) and clean(x, n)] if isinstance(value, list) else []


def requirement_problems(reqs, max_criteria):
    problems = []
    if not 1 <= len(reqs) <= max_criteria:
        problems.append(f"`requirements` needs 1 to {max_criteria} conditions, not {len(reqs)}")
    if len({r.lower() for r in reqs}) != len(reqs):
        problems.append("a requirement is repeated")
    for r in reqs:
        if len(r) < MIN_REQUIREMENT:
            problems.append(f"requirement too short to check: {r!r}")
        elif VAGUE.search(r):
            problems.append(f"requirement is not checkable: {r[:80]!r}")
    return problems


def field_problems(out):
    problems = [f"`{field}` is empty" for field in ("how_found", "root_cause") if not out[field]]
    if not 1 <= len(out["what_it_takes"]) <= MAX_TAKES:
        problems.append(f"`what_it_takes` needs 1 to {MAX_TAKES} statements, not {len(out['what_it_takes'])}")
    return problems


def secret_problems(out):
    kinds = triage.find_secrets(" ".join([out["how_found"], out["root_cause"]] + out["what_it_takes"] + out["requirements"]))
    return ["it contains " + ", ".join(kinds)] if kinds else []


def check(doc, max_criteria):
    if not isinstance(doc, dict):
        return None, ["the answer is not a JSON object"]
    out = {"how_found": clean(doc.get("how_found"), MAX_SENTENCE), "root_cause": clean(doc.get("root_cause"), MAX_SENTENCE),
           "what_it_takes": strings(doc.get("what_it_takes"), MAX_ITEM), "requirements": strings(doc.get("requirements"), MAX_ITEM)}
    return out, field_problems(out) + requirement_problems(out["requirements"], max_criteria) + secret_problems(out)
