FACTORY_CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap")
APP_CATEGORIES = ("spec_ambiguity", "model_limit", "regression")


def inferred_category(category, outcome, has_bugs=False):
    if outcome in ("budget_exhausted", "time_limit") and category in (None, "", "prompt_gap", "infra", "unknown", "model_limit"):
        return "model_limit"
    if outcome in ("watchdog_disabled", "regression") and category not in FACTORY_CATEGORIES:
        return "regression"
    if has_bugs and category not in FACTORY_CATEGORIES and category != "spec_ambiguity":
        return "regression"
    return category or None


def route(category):
    if category in FACTORY_CATEGORIES:
        return "factory"
    if category in APP_CATEGORIES:
        return "app"
    return "info"
