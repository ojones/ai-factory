# Step 4: the Retrospective Agent. It reads the facts, names a root-cause category, and edits a scratch copy of the Factory checkout with the smallest
# change that would have prevented the failure. The Orchestrator mints its credential, runs it in isolation, and copies back only allowed paths.
import filecmp
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from shared import agent_process, prompts, spend_budget, spend_ledger
from shared.console import log
from shared.shell import sh

CATEGORIES = ("prompt_gap", "template_gap", "orchestrator_gap", "plan_gap", "spec_ambiguity", "model_limit", "infra", "unknown")


# Where the retrospective Agent may propose changes. Never workflows (they hold the secrets), the Starter
# Template's protected files, or anything outside the Factory's own prompts, template, orchestrator and docs.
ALLOWED_PREFIXES = ("agents/", "templates/starter/", "orchestrator/", "STANDARDS", "ARCHITECTURE.md", "GLOSSARY.md")


DENIED_PREFIXES = (".github/", "templates/starter/.github/", "templates/starter/fly/", "templates/starter/fly.toml")


def allowed_path(path):
    return path.startswith(ALLOWED_PREFIXES) and not path.startswith(DENIED_PREFIXES) and ".." not in Path(path).parts


def mint_agent(cfg, parent_key):
    # (credential, budget): a single-model DeepInfra credential limited to `retrospective_cost_cap_usd`, so the Agent never
    # holds the parent key and one analysis cannot spend more than the cap. (None, None) if one cannot be minted.
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
    # Add what the Agent actually spent to the spend ledger, so the daily cap sees it (best effort, never fails the run).
    try:
        spent = budget.refresh(key)
        log(f"retrospective agent spent ${spent:.4f}")
        spend_ledger.record_spend_in_ledger({"app": "retrospective", "spent_usd": spent}, repo, f"{run_id}-pm", token)  # own id: the ledger counts a run id once
    except Exception as e:  # noqa: BLE001
        log(f"could not record the retrospective Agent's spend: {type(e).__name__}")


MAX_FILE_BYTES = 1_000_000


def agent_user():
    return os.environ.get("AGENT_USER") or None


def share_with(path, user):
    # Make what the Orchestrator just created readable and writable by the Agent user too (a copy's permissions drop the ACL's reach).
    if user:
        sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{user}:rwX,u:{os.environ.get('USER', 'runner')}:rwX", str(path)], check=False)


def listing(root):
    # ({relative path: file} for regular files, {relative path: target} for symlinks) of a tree, skipping `.git`.
    files, links = {}, {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                links[rel] = os.readlink(full)
            elif name in filenames:
                files[rel] = full
    return files, links


def tree_changes(before, after):
    # What the Agent did to its copy of the tree: ({path: "A" | "M" | "D"} for regular files, [symlinks it added or changed]). Two
    # plain trees are compared, never a git directory the Agent could have booby-trapped (a hook or config the Orchestrator would run).
    bf, bl = listing(before)
    af, al = listing(after)
    changes = {}
    for rel, full in af.items():
        if rel not in bf:
            changes[rel] = "A"
        elif not filecmp.cmp(bf[rel], full, shallow=False):
            changes[rel] = "M"
    for rel in bf:
        if rel not in af and rel not in al:
            changes[rel] = "D"
    return changes, sorted(rel for rel in al if bl.get(rel) != al[rel])


def apply_changes(before, after, changes):
    # Copy the Agent's changes into the Orchestrator's own checkout, only for paths the Agent may change and files of a sane size.
    # Returns the paths applied. Nothing the Agent made outside those paths ever reaches the checkout git runs in.
    applied = []
    for rel, kind in sorted(changes.items()):
        if not allowed_path(rel):
            continue
        dest = Path(before) / rel
        if kind == "D":
            dest.unlink(missing_ok=True)
        elif (Path(after) / rel).stat().st_size <= MAX_FILE_BYTES:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(after) / rel, dest)
        else:
            continue
        applied.append(rel)
    return applied


def scratch_root():
    # A fresh directory for one Agent run, inside the Agent user's area when isolation is on (the Orchestrator's own temp
    # directories are closed to it).
    base = Path(os.environ.get("BUILD_RUN_DIR") or tempfile.gettempdir())
    root = base / f"retrospective-{os.getpid()}-{int(time.time())}"
    root.mkdir(parents=True)
    return root


def run_tests(factory, root, user):
    # The orchestrator's unit tests over the Factory tree as it will be proposed, run as the Agent user in a throwaway copy with no
    # credential in its environment: the Agent may have edited test files, and a test is code. True when they pass.
    verify = root / "verify"
    shutil.copytree(factory, verify, ignore=shutil.ignore_patterns(".git", "node_modules"), symlinks=True)
    share_with(verify, user)
    env = {k: os.environ[k] for k in ("PATH", "LANG", "CI") if k in os.environ}
    env.update({"HOME": str(root / "home"), "TMPDIR": str(root / "tmp"), "PYTHONDONTWRITEBYTECODE": "1"})
    for name in ("tmp", "home"):
        (root / name).mkdir(exist_ok=True)
    share_with(root, user)
    out = root / "tests.out"
    rc = agent_process.run_watched([sys.executable, "-m", "unittest", "discover", "-p", "*_test.py", "orchestrator"], verify, env, out, 900, 0, user=user,
                       pidfile=root / "pgid-tests.txt")
    return rc == 0


def run_agent(factory, cfg, key, facts_path, result_path, timeout_min):
    # Run the retrospective Agent in a copy of the Factory tree, as the unprivileged Agent user when isolation is on (the same
    # account and self-check as the Build Run's Agents), with a scrubbed environment and a capped scoped key. Whatever it changes is
    # carried back into `factory` by `apply_changes`, only for allowed paths; its answer is copied to `result_path`. Returns False when
    # isolation is on but cannot be proven, in which case no Agent runs.
    user = agent_user()
    if user:
        problems = agent_process.run_isolation_probes(user)
        if problems:
            log("retrospective Agent not run, isolation is not effective: " + "; ".join(problems))
            return False
    root = scratch_root()
    try:
        work, io, home = root / "work", root / "io", root / "home"
        io.mkdir()
        home.mkdir()
        shutil.copytree(factory, work, ignore=shutil.ignore_patterns(".git", "node_modules"), symlinks=True)
        facts_copy, result_copy = io / "facts.json", io / "result.json"
        shutil.copyfile(facts_path, facts_copy)
        share_with(root, user)
        prompt = prompts.render(prompts.load_prompt(cfg["roles"]["retrospective"]["prompt"]), {
            "app_name": "-", "build_kind": "-", "facts_path": facts_copy, "result_path": result_copy,
            "categories": ", ".join(CATEGORIES)})
        env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR", "CI") if k in os.environ}
        env.update({"HOME": str(home), "LLM_MODEL": "openai/" + cfg["roles"]["retrospective"]["model"],
                    "LLM_BASE_URL": cfg["provider"]["base_url"], "LLM_API_KEY": key, "RUNTIME": "process"})
        rc = agent_process.run_watched(["openhands", "--headless", "--override-with-envs", "-t", prompt], work, env, root / "openhands.out",
                           timeout_min * 60, 0, user=user, pidfile=root / "pgid-agent.txt")
        if rc == "timeout":
            log("retrospective agent timed out")
        if result_copy.is_file():
            shutil.copyfile(result_copy, result_path)
        changes, links = tree_changes(factory, work)
        if links:
            log("retrospective Agent's symlinks ignored: " + ", ".join(links))
        applied = apply_changes(factory, work, changes)
        log(f"retrospective Agent changed {len(changes)} file(s); {len(applied)} in allowed paths carried over")
        return True
    finally:
        shutil.rmtree(root, ignore_errors=True)
