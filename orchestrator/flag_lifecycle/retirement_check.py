import re

RETIRE_RE = re.compile(r"^retire-flag: ([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\s*$", re.M)


def retire_slugs(task):
    return list(dict.fromkeys(RETIRE_RE.findall(task or "")))


COMMENT_START = ("//", "/*", "*", "#", "<!--")


def code_references(grep_lines):
    hits = []
    for line in grep_lines:
        parts = line.split(":", 3)
        if len(parts) == 4 and not parts[3].strip().startswith(COMMENT_START):
            hits.append(f"{parts[1]}:{parts[2]}")
    return hits


def retirement_problem(slug, hits):
    if not hits:
        return None
    return (f"The flag `{slug}` is still referenced in code: {', '.join(hits[:8])}. A retirement removes the flag's check (keep the behaviour it "
            "guarded, always on), its entry in `flags.json`, and its tests: delete each `withFlag(slug, false, ...)` test and unwrap each "
            "`withFlag(slug, true, ...)` test so its body runs on its own; no source, test or `flags.json` may mention the slug afterwards "
            "(a comment may).")
