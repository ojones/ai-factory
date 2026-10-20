# The cause of a run that did not release, named once (STEP 6.2) so the step after it can act on it: an app cause is fixed by a fix child under the
# same parent, a Factory cause by a fix request that becomes a learning PR, anything else is left for a person. The category comes from the
# Retrospective Agent when it ran, and is inferred from how the run ended when it did not.
from try_fix import fix_request


def name_cause(facts, result):
    # {"category": ..., "route": "app" | "factory" | "info"}; a run that released and found nothing has category None and route "info".
    category = fix_request.inferred_category((result or {}).get("category"), facts.get("outcome"), bool(facts.get("bugs")))
    return {"category": category, "route": fix_request.route(category)}
