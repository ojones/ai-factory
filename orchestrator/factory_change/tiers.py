import re

TIER_ONE = "tier_one"
TIER_TWO = "tier_two"
NEVER = "never"

TIER_TWO_PATTERNS = (
    r"orchestrator/build_run/run\.py",
    r"orchestrator/shared/(agent_runner|agent_process|spend_budget)\.py",
    r"orchestrator/retrospective/.*",
    r"orchestrator/try_fix/.*",
    r"orchestrator/factory_change/.*",
    r"agents/profiles\.yml",
)

NEVER_PATTERNS = (
    r"\.github/.*",
    r"templates/starter/\.github/.*",
    r"orchestrator/style_baseline\.json",
    r"pyproject\.toml",
    r".*\.(env|pem|key)",
)

TIER_ONE_PATTERNS = (
    r"orchestrator/.*",
    r"agents/prompts/.*",
    r"agents/replay/.*",
    r"agents/[a-z-]+fixtures?/.*",
    r"agents/planner-fixtures/.*",
)

PROMPT_PATH = re.compile(r"agents/prompts/.*")


def matches(path, patterns):
    return any(re.fullmatch(p, path) for p in patterns)


def classify(path):
    if ".." in path.split("/") or matches(path, NEVER_PATTERNS):
        return NEVER
    if matches(path, TIER_TWO_PATTERNS):
        return TIER_TWO
    return TIER_ONE if matches(path, TIER_ONE_PATTERNS) else NEVER


def kinds(paths):
    return {classify(p) for p in paths}


def merge_tier(paths):
    found = kinds(paths)
    if NEVER in found:
        return NEVER
    return TIER_TWO if TIER_TWO in found else TIER_ONE


def mixes_tiers(paths):
    return {TIER_ONE, TIER_TWO} <= kinds(paths)


def touches_prompt_path(paths):
    return any(PROMPT_PATH.fullmatch(p) for p in paths)


def tier_two_paths_text():
    return ", ".join(f"`{p.replace(chr(92) + '.', '.').replace('.*', '*')}`" for p in TIER_TWO_PATTERNS)
