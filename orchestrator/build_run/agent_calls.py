from shared import (
    agent_output,
    agent_runner,
    agent_usage,
    prompts,
)
from shared.console import log


class AgentCalls:
    def make_runner(self):
        self.runner = agent_runner.AgentRunner(self.cfg, self.meter, self.art, self.work, self.app_dir, self.agent_user,
                                               check_limits=lambda: self.check_limits(), on_spend=self.record_spend)

    def invoke(self, role, label, values, extra_env=None, cwd=None, home=None, note=None):
        prompt = prompts.render(prompts.load_prompt(self.cfg["roles"][role]["prompt"]), {"app_name": self.app,
                                                                         "spec": getattr(self, "spec", None) or getattr(self, "task", ""), **values})
        return self.runner.run(role, label, agent_output.retry_prompt(prompt, note), extra_env, cwd, home)

    def run_agent(self, role, label, values, extra_env=None):
        rc, self._last_cost, usage = self.invoke(role, label, values, extra_env)
        self._usage = agent_usage.merge_usage(self._usage, usage)
        return rc

    def take_usage(self):
        usage, self._usage = self._usage, None
        return usage

    def agent_json(self, role, label, values, path, extra_env=None, check=None, cwd=None, home=None):
        return agent_runner.json_output(
            lambda attempt_label, note: self.invoke(role, attempt_label, values, extra_env, cwd, home, note=note), path, role, label,
            lambda r, lab: self.art / f"openhands-{r}-{lab}.jsonl", cwd, check, restore=self.restore_tree,
            record_failed=lambda cost, message, usage: self.state.stage(f"{role.capitalize()} failed", role, label, cost, message, usage))

    def restore_tree(self, cwd=None):
        if self.git("status", "--porcelain", cwd=cwd).stdout.strip():
            log("A read-only Agent modified the working tree; restoring it.")
            self.git("reset", "-q", "--hard", "HEAD", cwd=cwd)
            self.git("clean", "-fdq", cwd=cwd)
