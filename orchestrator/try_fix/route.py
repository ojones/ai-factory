# Where a failed child goes next (STEP 6.2 to 7.5), from the cause the retrospective named: `app` (the code or the request was wrong: a bug Intake for the app), `factory`
# (a prompt, the planner, the Starter Template or the orchestrator was wrong: a learning PR) or `info` (no cause, or infrastructure: a person).
FACTORY_CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap")
APP_CATEGORIES = ("spec_ambiguity", "model_limit", "regression")


def inferred_category(category, outcome, has_bugs=False):
    # The cause to route by. A run that ran out of money or time was too big for its limits, which is the request's
    # problem: that decides the route unless the retrospective named a Factory cause that is not a prompt (an Agent that fails
    # because its credential ran dry looks like a prompt gap, which it is not). With no cause named, the same rule applies.
    if outcome in ("budget_exhausted", "time_limit") and category in (None, "", "prompt_gap", "infra", "unknown", "model_limit"):
        return "model_limit"
    if outcome in ("watchdog_disabled", "regression") and category not in FACTORY_CATEGORIES:
        return "regression"  # the change broke production: the story is retried after a fix
    if has_bugs and category not in FACTORY_CATEGORIES and category != "spec_ambiguity":
        return "regression"  # the tester saw checks fail: the story is retried on its own issue, with the bugs as notes
    return category or None


def route(category):
    # Where a fix request goes, from the cause the retrospective named: factory, app or info.
    if category in FACTORY_CATEGORIES:
        return "factory"
    if category in APP_CATEGORIES:
        return "app"
    return "info"
