import os
import time
from pathlib import Path

from shared import agent_output, agent_process, agent_usage, provider
from shared.console import log
from shared.run_stops import NeedsHuman, ProviderBlocked


class AgentRunner:
    def __init__(self, cfg, budget, art_dir, work_dir, default_cwd, agent_user=None, check_limits=lambda: None, on_spend=None):
        self.cfg, self.budget = cfg, budget
        self.art, self.work, self.default_cwd = Path(art_dir), Path(work_dir), default_cwd
        self.agent_user = agent_user
        self.check_limits = check_limits
        self.on_spend = on_spend or (lambda jwt: sum(budget.tokens.values()))

    def model_for(self, role, label):
        profile = self.cfg["roles"][role]
        if role == "coder" and str(label) != "1" and profile.get("fix_model"):
            return profile["fix_model"]
        return profile["model"]

    def agent_env(self, role, jwt, extra=None, home=None, model=None):
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR", "CI") if k in os.environ}
        if home:
            env["HOME"] = str(home)
        profile = self.cfg["roles"][role]
        env.update({"LLM_MODEL": "openai/" + (model or profile["model"]), "LLM_BASE_URL": self.cfg["provider"]["base_url"],
                    "LLM_API_KEY": jwt, "RUNTIME": "process"})
        env.update(extra or {})
        return env

    def log_path(self, role, label):
        return self.art / f"openhands-{role}-{label}.jsonl"

    def agent_home(self, home):
        home = home or (self.work / "home-agent" if self.agent_user else None)
        if home:
            Path(home).mkdir(parents=True, exist_ok=True)
        return home

    def launch(self, role, label, prompt, jwt, model, extra_env, cwd, home, jsonl):
        limits = self.cfg["limits"]
        stall_seconds = float(limits.get("agent_stall_minutes", 0)) * 60
        rc = agent_process.run_watched(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd or self.default_cwd,
                                       self.agent_env(role, jwt, extra_env, home, model), jsonl, limits["agent_timeout_minutes"] * 60,
                                       stall_seconds, user=self.agent_user, pidfile=self.work / f"pgid-{role}-{label}.txt")
        if rc == "stall":
            log(f"{role} ({label}): no output for {limits.get('agent_stall_minutes')} minutes; killed it so the attempt can restart")
        return rc

    def raise_if_provider_blocked(self, role, label, jsonl):
        blocked = provider.scan_for_provider_block(jsonl)
        if blocked:
            log(f"{role} ({label}): {blocked}")
            raise ProviderBlocked(blocked)

    def context_line(self, role, label, usage):
        goal = self.cfg["limits"].get("context_goal_tokens", 100000)
        over = f" (over the {goal:,} goal)" if usage["peak_context"] > goal else ""
        return (f"{role} ({label}) context: {usage['calls']} calls, peak {usage['peak_context']:,} tokens; "
                f"{usage['seconds']:.0f}s wall, {usage['llm_seconds']:.0f}s in the model{over}")

    def log_run(self, role, label, rc, cost, after, usage):
        lines = [f"::group::{role} ({label})", f"{role} ({label}) exited {rc}; cost ${cost:.4f}; run total ${after:.4f} of ${self.budget.cap:.2f}", "::endgroup::"]
        if usage:
            lines.insert(2, self.context_line(role, label, usage))
        for line in lines:
            log(line)

    def run(self, role, label, prompt, extra_env=None, cwd=None, home=None):
        self.check_limits()
        model = self.model_for(role, label)
        jwt = self.budget.mint(model)
        home = self.agent_home(home)
        jsonl = self.log_path(role, label)
        known = self.conversation_dirs(home)
        began = time.time()
        rc = self.launch(role, label, prompt, jwt, model, extra_env, cwd, home, jsonl)
        after = self.on_spend(jwt)
        self.raise_if_provider_blocked(role, label, jsonl)
        usage = self.collect_usage(role, label, known, home)
        if usage:
            usage["seconds"] = round(time.time() - began, 1)
        cost = self.budget.tokens[jwt]
        self.log_run(role, label, rc, cost, after, usage)
        return rc, cost, usage

    def conversations_root(self, home=None):
        return Path(home or os.environ.get("HOME", "~")).expanduser() / ".openhands" / "conversations"

    def conversation_dirs(self, home=None):
        root = self.conversations_root(home)
        return {p.name for p in root.iterdir()} if root.is_dir() else set()

    def collect_usage(self, role, label, known, home=None):
        root = self.conversations_root(home)
        for name in sorted(self.conversation_dirs(home) - known):
            src = root / name / "base_state.json"
            doc = agent_output.load_json(src)
            if doc is not None:
                (self.art / f"openhands-{role}-{label}-state.json").write_text(src.read_text())
                return agent_usage.summarize_token_usage(doc)
        return None


def accepted(doc, check):
    try:
        return doc is not None and (check is None or check(doc) is not False)
    except (ValueError, AttributeError, TypeError):
        return False


def no_output_error(role, total_cost, note, exhausted):
    problem = f" (last problem: {note})" if note else ""
    if exhausted:
        return NeedsHuman("other", f"the {role} spent its whole credential (${total_cost:.2f}) without writing a usable output file{problem}; a second attempt would only repeat it")
    return NeedsHuman("other", f"the {role} produced no valid output file twice{problem}")


def json_output(attempt, path, role, label, log_path, cwd=None, check=None, restore=lambda cwd: None, record_failed=lambda cost, message, usage: None):
    total_cost, usage, note, attempts, exhausted = 0.0, None, None, 0, False
    for n in (1, 2):
        Path(path).unlink(missing_ok=True)
        attempt_label = f"{label}{'' if n == 1 else 'b'}"
        _, cost, used = attempt(attempt_label, note)
        attempts += 1
        total_cost += cost
        usage = agent_usage.merge_usage(usage, used)
        agent_output.adopt_misplaced_file(path, cwd)
        doc = agent_output.load_json(path)
        if accepted(doc, check):
            return doc, total_cost, usage
        note = agent_output.json_problem(path, check)
        restore(cwd)
        if provider.spending_limit_hit(log_path(role, attempt_label)):
            exhausted = True
            break
    record_failed(total_cost, f"no usable output after {attempts} attempt(s)", usage)
    raise no_output_error(role, total_cost, note, exhausted)
