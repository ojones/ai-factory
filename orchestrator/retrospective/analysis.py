from shared import agent_output

from retrospective import agent_run, tracker


def comment_on_all(repo, token, targets, text):
    for n in targets:
        tracker.gh(["issue", "comment", str(n), "--repo", repo, "--body", text], token)


def analyse(factory, cfg, repo, token, parent_key, facts_path, result_path, targets, run_id):
    key, budget = agent_run.mint_agent(cfg, parent_key)
    if not key:
        return None
    result_path.unlink(missing_ok=True)
    ran = agent_run.run_agent(factory, cfg, key, facts_path, result_path, int(cfg["limits"].get("retrospective_timeout_minutes", 15)))
    agent_run.record_agent_spend(budget, key, repo, token, run_id)
    result = agent_output.load_json(result_path) or {} if ran else {}
    if result.get("category") in agent_run.CATEGORIES:
        comment_on_all(repo, token, targets, f"**Retrospective** ({result['category']}): {result.get('root_cause', '')}")
        return result
    if ran:
        comment_on_all(repo, token, targets, "The retrospective Agent produced no usable analysis.")
    return None
