from try_fix import route


def name_cause(facts, result):
    category = route.inferred_category((result or {}).get("category"), facts.get("outcome"), bool(facts.get("bugs")))
    return {"category": category, "route": route.route(category)}
