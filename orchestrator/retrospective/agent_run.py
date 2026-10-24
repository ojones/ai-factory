import os
import shutil
import tempfile
import time
from pathlib import Path

from shared import agent_process, prompts, spend_budget, spend_ledger
from shared.console import log
from shared.shell import sh

CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap", "spec_ambiguity", "model_limit", "infra", "unknown")


def mint_agent(cfg, parent_key):
    try:
        limits = cfg["limits"]
        budget = spend_budget.Budget(parent_key, float(limits.get("retrospective_cost_cap_usd", 0.5)), int(limits["jwt_ttl_seconds"]))
        return budget.mint(cfg["roles"]["retrospective"]["model"]), budget
    except Exception as e:  # noqa: BLE001 - never fail the run
        log(f"could not mint a scoped credential for the retrospective Agent: {type(e).__name__}")
        return None, None


def mint_agent_key(cfg, parent_key):
    return mint_agent(cfg, parent_key)[0]


def record_agent_spend(budget, key, repo, token, run_id):
    try:
        spent = budget.refresh(key)
        log(f"retrospective agent spent ${spent:.4f}")
        spend_ledger.record_spend_in_ledger({"app": "retrospective", "spent_usd": spent}, repo, f"{run_id}-pm", token)
    except Exception as e:  # noqa: BLE001
        log(f"could not record the retrospective Agent's spend: {type(e).__name__}")


def agent_user():
    return os.environ.get("AGENT_USER") or None


def share_with(path, user):
    if user:
        sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{user}:rwX,u:{os.environ.get('USER', 'runner')}:rwX", str(path)], check=False)


def scratch_root():
    base = Path(os.environ.get("BUILD_RUN_DIR") or tempfile.gettempdir())
    root = base / f"retrospective-{os.getpid()}-{int(time.time())}"
    root.mkdir(parents=True)
    return root


def copy_workspace(root, factory, facts_path):
    work, io, home = root / "work", root / "io", root / "home"
    io.mkdir()
    home.mkdir()
    shutil.copytree(factory, work, ignore=shutil.ignore_patterns(".git", "node_modules"), symlinks=True)
    facts_copy = io / "facts.json"
    shutil.copyfile(facts_path, facts_copy)
    return work, home, facts_copy, io / "result.json"


def retrospective_prompt(cfg, facts_copy, result_copy):
    values = {"app_name": "-", "build_kind": "-", "facts_path": facts_copy, "result_path": result_copy, "categories": ", ".join(CATEGORIES)}
    return prompts.render(prompts.load_prompt(cfg["roles"]["retrospective"]["prompt"]), values)


def retrospective_env(cfg, key, home):
    env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR", "CI") if k in os.environ}
    env.update({"HOME": str(home), "LLM_MODEL": "openai/" + cfg["roles"]["retrospective"]["model"],
                "LLM_BASE_URL": cfg["provider"]["base_url"], "LLM_API_KEY": key, "RUNTIME": "process"})
    return env


def run_agent(factory, cfg, key, facts_path, result_path, timeout_min):
    user = agent_user()
    problems = agent_process.run_isolation_probes(user) if user else []
    if problems:
        log("retrospective Agent not run, isolation is not effective: " + "; ".join(problems))
        return False
    root = scratch_root()
    try:
        work, home, facts_copy, result_copy = copy_workspace(root, factory, facts_path)
        share_with(root, user)
        prompt = retrospective_prompt(cfg, facts_copy, result_copy)
        rc = agent_process.run_watched(["openhands", "--headless", "--override-with-envs", "-t", prompt], work, retrospective_env(cfg, key, home),
                                       root / "openhands.out", timeout_min * 60, 0, user=user, pidfile=root / "pgid-agent.txt")
        if rc == "timeout":
            log("retrospective agent timed out")
        if result_copy.is_file():
            shutil.copyfile(result_copy, result_path)
        return True
    finally:
        shutil.rmtree(root, ignore_errors=True)
