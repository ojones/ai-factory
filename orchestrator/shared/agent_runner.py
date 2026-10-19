# Running one Agent: a headless OpenHands invocation with a single-model scoped credential, a whitelisted environment, a stall watch, and the cost and
# context it used read back afterwards. The caller supplies the prompt and the few things that belong to its own run (limits, spend record).
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
        self.check_limits = check_limits  # raises when the run's cap or time is used up; asked before every invocation
        self.on_spend = on_spend or (lambda jwt: sum(budget.tokens.values()))  # told which credential just spent, returns the run's total so far

    def model_for(self, role, label):
        # The role's model. The coder may name a stronger `fix_model` for every attempt after round 1.
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

    def run(self, role, label, prompt, extra_env=None, cwd=None, home=None):
        # One headless OpenHands invocation. Safe to call from several threads at once when each has its own `home` (OpenHands keeps its
        # conversations there) and `cwd`. Returns (exit status, or 'timeout' / 'stall' if killed; cost; token usage).
        self.check_limits()
        limits = self.cfg["limits"]
        model = self.model_for(role, label)
        jwt = self.budget.mint(model)
        if self.agent_user and not home:
            home = self.work / "home-agent"  # the runner's own home is closed to the Agent user
        if home:
            Path(home).mkdir(parents=True, exist_ok=True)
        jsonl = self.log_path(role, label)
        known = self.conversation_dirs(home)
        began = time.time()
        rc = agent_process.run_watched(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt], cwd or self.default_cwd,
                                       self.agent_env(role, jwt, extra_env, home, model), jsonl, limits["agent_timeout_minutes"] * 60,
                                       float(limits.get("agent_stall_minutes", 0)) * 60, user=self.agent_user,
                                       pidfile=self.work / f"pgid-{role}-{label}.txt")
        if rc == "stall":
            log(f"{role} ({label}): no output for {limits.get('agent_stall_minutes')} minutes; killed it so the attempt can restart")
        after = self.on_spend(jwt)
        blocked = provider.scan_for_provider_block(jsonl)
        if blocked:  # the account ran dry (possibly mid-run): stop everything, do not count it as the Agent's failure
            log(f"{role} ({label}): {blocked}")
            raise ProviderBlocked(blocked)
        usage = self.collect_usage(role, label, known, home)
        if usage:
            usage["seconds"] = round(time.time() - began, 1)  # wall time; minus llm_seconds is tool and wait time
        cost = self.budget.tokens[jwt]
        lines = [f"::group::{role} ({label})",
                 f"{role} ({label}) exited {rc}; cost ${cost:.4f}; run total ${after:.4f} of ${self.budget.cap:.2f}", "::endgroup::"]
        if usage:
            goal = limits.get("context_goal_tokens", 100000)
            lines.insert(2, f"{role} ({label}) context: {usage['calls']} calls, peak {usage['peak_context']:,} tokens; "
                         f"{usage['seconds']:.0f}s wall, {usage['llm_seconds']:.0f}s in the model"
                         + (f" (over the {goal:,} goal)" if usage["peak_context"] > goal else ""))
        for line in lines:
            log(line)
        return rc, cost, usage

    def conversations_root(self, home=None):
        return Path(home or os.environ.get("HOME", "~")).expanduser() / ".openhands" / "conversations"

    def conversation_dirs(self, home=None):
        root = self.conversations_root(home)
        return {p.name for p in root.iterdir()} if root.is_dir() else set()

    def collect_usage(self, role, label, known, home=None):
        # Read the conversation this invocation created and keep its raw state as an artifact.
        root = self.conversations_root(home)
        for name in sorted(self.conversation_dirs(home) - known):
            src = root / name / "base_state.json"
            doc = agent_output.load_json(src)
            if doc is not None:
                (self.art / f"openhands-{role}-{label}-state.json").write_text(src.read_text())
                return agent_usage.summarize_token_usage(doc)
        return None


def json_output(attempt, path, role, label, log_path, cwd=None, check=None, restore=lambda cwd: None, record_failed=lambda cost, message, usage: None):
    # Run a role that writes a JSON file; one retry if the file is missing or malformed. `attempt(attempt_label, note)` runs the Agent and returns
    # (exit status, cost, usage); `note` tells it what was wrong with the first try. If the Agent wrote the file under its working directory instead
    # of the path it was given (it has done so, twice, with the right content), that copy is used. Returns (document, cost, token usage).
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
        try:
            if doc is not None and (check is None or check(doc) is not False):
                return doc, total_cost, usage
        except (ValueError, AttributeError, TypeError):
            pass
        note = agent_output.json_problem(path, check)  # read before the next attempt removes the file
        restore(cwd)
        if provider.spending_limit_hit(log_path(role, attempt_label)):
            # The Agent spent its whole credential and still wrote nothing usable. A second attempt gets a credential of the same size and goes
            # the same way, so it only spends the money again (a tester did this for about $0.50 a time).
            exhausted = True
            break
    # What a failed Agent cost is spent either way; let the caller account for it.
    record_failed(total_cost, f"no usable output after {attempts} attempt(s)", usage)
    if exhausted:
        raise NeedsHuman("other", f"the {role} spent its whole credential (${total_cost:.2f}) without writing a usable output file"
                                  + (f" (last problem: {note})" if note else "") + "; a second attempt would only repeat it")
    raise NeedsHuman("other", f"the {role} produced no valid output file twice" + (f" (last problem: {note})" if note else ""))
