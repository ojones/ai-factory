import json
import shutil
from pathlib import Path

from retrospective import agent_run
from shared import agent_output, prompts

ROLE = "factory_coder"


def scratch_copy(factory, work):
    scratch = Path(work) / "factory-copy"
    shutil.rmtree(scratch, ignore_errors=True)
    shutil.copytree(factory, scratch, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"), symlinks=True)
    return scratch


def findings_file(work, blocking):
    path = Path(work) / "findings.json"
    path.write_text(json.dumps({"blocking": blocking, "minor": []}), encoding="utf-8")
    return path


def coder_prompt(cfg, task, round_no, findings_path, result_path):
    values = {"task": task, "round": round_no, "findings_path": findings_path, "result_path": result_path}
    return prompts.render(prompts.load_prompt(cfg["roles"][ROLE]["prompt"]), values)


def usable_result(path):
    doc = agent_output.load_json(path)
    return doc if isinstance(doc, dict) and isinstance(doc.get("reproduction"), str) else None


def write_change(cfg, runner, factory, work, task, round_no, blocking=()):
    scratch = scratch_copy(factory, work)
    result_path = Path(work) / "coder-result.json"
    result_path.unlink(missing_ok=True)
    prompt = coder_prompt(cfg, task, round_no, findings_file(work, list(blocking)), result_path)
    agent_run.share_with(work, runner.agent_user)
    runner.run(ROLE, str(round_no), prompt, cwd=scratch)
    agent_run.carry_over_changes(factory, scratch)
    return usable_result(result_path)
