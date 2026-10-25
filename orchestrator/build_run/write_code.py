import json
import os
import subprocess

from flag_lifecycle import (
    retirement_check,
)
from planning import secrets_check, triage
from shared import (
    agent_process,
    run_stops,
    starter_template,
)
from shared.console import log
from shared.shell import sh

from build_run import endings

UNREADABLE = object()


class WriteCode:
    def coder(self, label, task, findings_path):
        task0, attempts = task, 0
        base = self.head()
        while True:
            self.run_agent("coder", label, {"round": label, "task": task, "findings_path": findings_path,
                                            "issue_ref": f"{self.factory_repo}#{self.issue}"})
            cost, head = self._last_cost, self.head()
            problem = self.commit_problem(base, head)
            if not problem:
                return self.accept_commit(label, cost, head)
            attempts += 1
            self.state.stage("Coder", "coder", label, cost, f"rejected: {problem[:60]}", self.take_usage())
            if attempts >= 3:
                raise run_stops.NeedsHuman("other", f"the coder could not produce an acceptable commit: {problem}")
            task = f"{problem}\n\nOriginal task:\n{task0}"

    def accept_commit(self, label, cost, head):
        self.check_limits()
        self.require_found_secrets(head)
        self.state.stage("Coder", "coder", label, cost, f"committed {head[:8]}", self.take_usage())
        return head

    def commit_problem(self, base, head):
        if head == base:
            return "You made no commit. Make the change, then run `git add` and `git commit`."
        if self.git("merge-base", "--is-ancestor", base, head, check=False).returncode != 0:
            self.git("reset", "-q", "--hard", base)
            return "You rewrote history. Add new commits on top of the existing ones only."
        return self.content_problem(base, head)

    def content_problem(self, base, head):
        changed = self.git("diff", "--name-only", f"{base}..{head}").stdout.split("\n")
        bad = starter_template.protected_violations([c for c in changed if c])
        if bad:
            self.git("reset", "-q", "--hard", base)
            return f"Your commits changed protected Starter Template files ({', '.join(bad)}). They were discarded. Redo the work without touching them."
        return self.retirement_problem_in(head) or self.secret_problem(base, head) or (self.check_problem() if self.lim.get("precheck", True) else None)

    def retirement_problem_in(self, head):
        for slug in self.retiring:
            references = retirement_check.code_references(self.git("grep", "-n", "-I", "-F", "-e", slug, head, check=False).stdout.splitlines())
            problem = retirement_check.retirement_problem(slug, references)
            if problem:
                return problem
        return None

    def secrets_in(self, ref):
        shown = self.git("show", f"{ref}:secrets.json", check=False)
        if shown.returncode != 0:
            return None
        try:
            return [{"name": x.get("name"), "purpose": str(x.get("purpose", ""))} for x in json.loads(shown.stdout).get("secrets", [])]
        except (ValueError, AttributeError):
            return UNREADABLE

    def require_found_secrets(self, head):
        found = self.undeclared_secrets_in(head)
        if not found:
            return
        self.declared_secrets = [*self.declared_secrets, *found]
        missing = self.missing_of(self.declared_secrets)
        retry = "add `proceed-with-change` again"
        self.gh(["issue", "comment", self.issue, "--repo", self.factory_repo, "--body",
                 secrets_check.request_comment(self.declared_secrets, missing, self.app_repo, retry)], token=self.factory_token)
        if missing:
            raise endings.AwaitingSecret(secrets_check.waiting_message(missing, self.app_repo, retry))

    def undeclared_secrets_in(self, head):
        listed = self.secrets_in(head)
        known = {x["name"] for x in self.declared_secrets}
        return [x for x in listed if x["name"] not in known] if isinstance(listed, list) else []

    def secret_value_problem(self, base, head):
        kinds = triage.diff_secrets(self.git("diff", f"{base}..{head}", check=False).stdout)
        if not kinds:
            return None
        self.git("reset", "-q", "--hard", base)
        return (f"Your commit added {' and '.join(kinds)}. The repository is public and secrets never go in code. It was discarded. Read the value "
                "from process.env at runtime and, in tests, use an obviously fake placeholder.")

    def secret_problem(self, base, head):
        value_problem = self.secret_value_problem(base, head)
        listed = self.secrets_in(head)
        if value_problem or listed is None:
            return value_problem
        if listed is UNREADABLE:
            return "`secrets.json` is not valid JSON of the form {\"secrets\": [{\"name\": \"...\", \"purpose\": \"...\"}]}."
        problems = [triage.secret_name_problem(x["name"]) for x in listed]
        return next((f"`secrets.json` cannot list that: {p}." for p in problems if p), None)

    def check_problem(self):
        try:
            scripts = json.loads((self.app_dir / "package.json").read_text()).get("scripts", {})
        except (OSError, ValueError):
            return None
        if "check" not in scripts:
            return None
        self.restore_tree()
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR", "CI") if k in os.environ}
        try:
            p = sh(agent_process.agent_command(["npm", "run", "check"], env, self.agent_user), cwd=self.app_dir, env=env, check=False, timeout=300)
        except (subprocess.TimeoutExpired, OSError) as e:
            log(f"npm run check could not be run ({type(e).__name__}); leaving it to the Test Gate")
            return None
        finally:
            self.restore_tree()
        if p.returncode == 0:
            return None
        out = ((p.stdout or "") + (p.stderr or "")).strip()[-1500:]
        return f"`npm run check` fails on your commit. Fix every error it reports (in the code, not by suppressing the rule), then commit again:\n{out}"
