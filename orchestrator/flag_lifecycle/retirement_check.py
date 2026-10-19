# The rules a flag retirement is held to: the `retire-flag:` lines in a task, and no code may mention a retiring slug afterwards.
import re

RETIRE_RE = re.compile(r"^retire-flag: ([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\s*$", re.M)  # one line per flag to retire


def retire_slugs(task):
    # The slugs a task asks to retire (its `retire-flag: <slug>` lines), in order, without repeats.
    return list(dict.fromkeys(RETIRE_RE.findall(task or "")))


COMMENT_START = ("//", "/*", "*", "#", "<!--")


def code_references(grep_lines):
    # The `git grep -n <tree> -e slug` hits that are code, not comments. The grep covers the whole tree, so source, tests (a `withFlag(slug, ...)`
    # call) and `flags.json` all count. Format: <tree>:<path>:<line>:<text>.
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
