from build_run import review_code
from shared import prompts
from shared.shell import sh

ROLE = "factory_reviewer"


def numbered(text):
    return "\n".join(f"{i}: {line}" for i, line in enumerate(text.split("\n"), 1))


def changed_files(factory):
    return [p for p in sh(["git", "diff", "--cached", "--name-only", "--diff-filter=d", "HEAD"], cwd=factory).stdout.splitlines() if p]


def build_context(factory, ticket, max_chars):
    parts = [f"# The ticket (the spec for this change)\n{ticket}", f"# Diff\n{sh(['git', 'diff', '--cached', 'HEAD'], cwd=factory).stdout}"]
    for path in changed_files(factory):
        parts.append(f"# File: {path}\n{numbered((factory / path).read_text(encoding='utf-8', errors='replace'))}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        raise review_code.ContextTooLarge(f"{len(text):,} characters of context against a limit of {max_chars:,}")
    return text


def ask(cfg, budget, system, context):
    role = cfg["roles"][ROLE]
    jwt = budget.mint(role["model"])
    try:
        return review_code.single_call_review(cfg["provider"]["base_url"], jwt, role["model"], system, context)[0]
    finally:
        budget.refresh(jwt)


def review(cfg, budget, factory, ticket):
    context = build_context(factory, ticket, int(cfg["limits"].get("review_context_max_chars", 200000)))
    system = prompts.render(prompts.load_prompt(cfg["roles"][ROLE]["prompt"]), {})
    clean, blocking, minor = review_code.derive_review(ask(cfg, budget, system, context))
    return clean, blocking, minor
