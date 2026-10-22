import contextlib
import json
import os
import re
import shutil
import subprocess
import time

from flag_lifecycle import (
    flag_slug,
    retirement_selection,
)
from planning import secrets_check, secrets_marker, triage
from request import read_form
from shared import (
    agent_process,
    child_tickets,
    config,
    github,
    preview_token,
    provider,
    run_stops,
    spend_budget,
    spend_ledger,
    starter_template,
)
from shared.console import log
from shared.shell import sh

from build_run import endings, read_child, verify_deployed_app

DEPLOY_WORKFLOW = ".github/workflows/deploy-fly.yml"


SECRETS_REGION_RE = re.compile(r"^([ \t]*)# factory-secrets:begin\n(?:.*\n)*?[ \t]*# factory-secrets:end$", re.M)


def static_secret_reference(indent, name):
    return f"{indent}{name}: ${{{{ secrets.{name} }}}}"


def wire_secrets(workflow_text, names):
    names = sorted({n for n in names if isinstance(n, str) and not triage.secret_name_problem(n)})

    def region(m):
        indent = m.group(1)
        return "\n".join([f"{indent}# factory-secrets:begin"] + [static_secret_reference(indent, n) for n in names] + [f"{indent}# factory-secrets:end"])
    return SECRETS_REGION_RE.sub(region, workflow_text, count=1)


class PrepareRun:
    def read_issue(self):
        out = self.gh(["issue", "view", self.issue, "--repo", self.factory_repo, "--json", "title,body,labels,comments"], token=self.factory_token).stdout
        return json.loads(out)

    def read_plan_meta(self, issue):
        self.plan_meta = read_child.identify_intake(issue, self.app, self.issue)
        self.locate_plan()
        self.fix_for = self.plan_meta.get("fix_for")
        if self.fix_for:
            self.state.d["fix_for"] = self.fix_for

    def read_request(self, issue):
        body = issue["body"] or ""
        self.task, self.cap = read_child.parse_intake(body, self.lim["cost_cap_usd_default"], self.lim["cost_cap_usd_ceiling"])
        secrets = triage.find_secrets(body)
        if secrets:
            raise endings.Refused(triage.secret_refusal(secrets))
        self.declared_secrets = secrets_marker.declared_secrets(issue)
        if self.declared_secrets:
            self.require_secrets(self.declared_secrets)
            self.task += secrets_check.secrets_note(self.declared_secrets) if self.plan_meta else ""
        self.spec = self.task
        self.cap_override = self.requested_cap_override(issue)
        self.issue_title = issue.get("title", "")

    def record_limits(self):
        self.state.d["cap_usd"] = self.cap
        self.state.d["context_goal_tokens"] = self.lim.get("context_goal_tokens", 100000)
        self.state.save()

    def check_before_spending(self):
        self.check_daily_cap()
        self.prepare_agent_user()
        self.check_models()
        self.wait_for_capacity()

    def start_metering(self):
        self.meter = spend_budget.Budget(os.environ["DEEPINFRA_API_KEY"], self.cap, self.lim["jwt_ttl_seconds"])
        self.make_runner()
        self.preview = preview_token.for_app(os.environ["PREVIEW_MASTER_SECRET"], self.app)
        print(f"::add-mask::{self.preview}", flush=True)

    def prepare_checkout(self, issue):
        self.clone_without_storing_credential()
        self.install_dependencies()
        self.git("config", "user.name", "ai-factory-coder")
        self.git("config", "user.email", "coder@ai-factory.local")
        labels = {l["name"] for l in issue.get("labels", [])}
        self.apply_template_files(labels)
        self.state.d["base_sha"] = self.head()
        self.stage_template_config(labels)

    def setup(self):
        issue = self.read_issue()
        self.read_plan_meta(issue)
        self.read_request(issue)
        self.record_limits()
        self.check_before_spending()
        self.start_metering()
        self.prepare_checkout(issue)
        self.state.d["build_kind"] = self.build_kind
        self.retiring = self.choose_flags_to_retire()
        self.state.save()
        log(f"Intake #{self.issue}: app {self.app}, cap ${self.cap:.2f}, base {self.state.d['base_sha'][:8]}")

    def requested_cap_override(self, issue):
        raw_cap = read_form.form_section(issue["body"] or "", "Cost cap override (USD)").lstrip("$")
        return raw_cap if raw_cap and raw_cap != "_No response_" else None

    def clone_without_storing_credential(self):
        sh(["git", "clone", "-q", f"https://github.com/{self.app_repo}.git", str(self.app_dir)],
           env={**os.environ, **github.git_auth_env(self.auth_header)})
        self.share_with_agent(self.app_dir)

    def locate_plan(self):
        found = child_tickets.parent_info(self.factory_repo, self.issue, self.factory_token, lambda args, token: self.gh(args, token=token, check=False))
        read_child.require_planned(self.issue, self.plan_meta, found)
        self.parent = found["number"]
        self.state.d["parent"] = self.parent

    def require_secrets(self, needed):
        try:
            have = secrets_check.present_names(lambda args: self.gh(args, check=False), self.app_repo)
        except secrets_check.SecretsUnreadable as e:
            raise run_stops.NeedsHuman("other", str(e))
        self.state.d["secrets"] = [x["name"] for x in needed]
        missing = secrets_check.missing_secrets(needed, have)
        if missing:
            raise endings.AwaitingSecret(secrets_check.waiting_message(missing, self.app_repo, "add `proceed-with-change` again"))

    def copy_template_files(self, group):
        changed = []
        for rel in group:
            src, dst = config.FACTORY_DIR / "templates" / "starter" / rel, self.app_dir / rel
            if not src.is_file():
                continue
            wanted = self.content_keeping_declared_secrets(rel, src.read_bytes())
            if not dst.is_file() or dst.read_bytes() != wanted:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(wanted)
                changed.append(rel)
        if changed:
            self.git("add", "--", *changed)
            self.git("-c", "user.name=ai-factory-orchestrator", "-c", "user.email=orchestrator@ai-factory.local", "commit", "-q", "-m",
                     "chore: sync protected Starter Template files\n\n" + "\n".join(changed))
            self.share_with_agent(self.app_dir)
        return changed

    def content_keeping_declared_secrets(self, rel, content):
        if rel != DEPLOY_WORKFLOW:
            return content
        return wire_secrets(content.decode(), self.secret_names()).encode()

    def secret_names(self):
        names = list(self.state.d.get("secrets") or [])
        with contextlib.suppress(OSError, ValueError, AttributeError):
            names += [x.get("name") for x in json.loads((self.app_dir / "secrets.json").read_text()).get("secrets", [])]
        return names

    def stage_secret_wiring(self):
        if not self.state.d.get("secrets"):
            return
        try:
            if self.copy_template_files((DEPLOY_WORKFLOW,)):
                log("listed the declared secrets in the deploy workflow: " + ", ".join(self.state.d["secrets"]))
        except Exception as e:  # noqa: BLE001
            log(f"could not list the secrets in the deploy workflow: {type(e).__name__}: {e}")

    def apply_template_files(self, labels):
        if "template-sync" not in labels:
            return
        try:
            changed = self.copy_template_files(starter_template.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR)
            if changed:
                sh(["git", "push", "-q", "origin", "HEAD:main"], cwd=self.app_dir, env={**os.environ, **github.git_auth_env(self.auth_header)})
                log("synced protected template files: " + ", ".join(changed))
        except Exception as e:  # noqa: BLE001
            log(f"could not sync protected template files: {type(e).__name__}: {e}")

    def stage_template_config(self, labels):
        if "template-sync" not in labels:
            return
        try:
            changed = self.copy_template_files(starter_template.TEMPLATE_FILES_HELD)
            if changed:
                log("staged protected lint config, pushed with the coder's work: " + ", ".join(changed))
        except Exception as e:  # noqa: BLE001
            log(f"could not stage the lint config: {type(e).__name__}: {e}")

    def choose_flags_to_retire(self):
        picked, issues = retirement_selection.choose(
            not self.fix_for, self.task, self.app_repo.split("/")[0], self.app,
            self.pat, self.lim.get("flag_retirement") or {}, self.git("show", "HEAD:flags.json", check=False).stdout,
            time.strftime("%Y-%m-%d", time.gmtime()))
        if issues:
            self.flag_issues = issues
        return picked

    def swap_unserved_model(self, role, profile, status):
        model = profile["model"]
        if status(model) != "missing":
            return None
        fallback = profile.get("fallback_model")
        if not fallback or status(fallback) == "missing":
            reason = f"its fallback `{fallback}` is not either" if fallback else "the role has no `fallback_model`"
            raise run_stops.NeedsHuman("other", f"the {role} model `{model}` is no longer served by the provider and {reason}: choose a model in agents/profiles.yml")
        profile["model"] = fallback
        log(f"{role}: `{model}` is not served by the provider; using its fallback `{fallback}` for this run")
        return {"from": model, "to": fallback}

    def check_models(self):
        base, key = self.cfg["provider"]["base_url"], os.environ["DEEPINFRA_API_KEY"]
        seen = {}

        def status(model):
            if model not in seen:
                seen[model] = provider.model_status(base, key, model)
            return seen[model]

        roles = [r for r in ("coder", "tester", "reviewer") if self.cfg["roles"].get(r)]
        swaps = {role: self.swap_unserved_model(role, self.cfg["roles"][role], status) for role in roles}
        swapped = {role: swap for role, swap in swaps.items() if swap}
        if swapped:
            self.state.d["fallbacks"] = swapped
            self.state.save()

    def prepare_agent_user(self):
        if not self.agent_user:
            return
        tools = self.work / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copy(verify_deployed_app.API_CHECK, tools / "api_check.py")
        shutil.copy(verify_deployed_app.UI_CHECK, tools / "ui_check.py")
        self.api_check_path = str(tools / "api_check.py")
        self.ui_check_path = str(tools / "ui_check.py")
        problems = self.isolation_self_check()
        self.state.d["isolation"] = {"user": self.agent_user, "problems": problems}
        self.state.save()
        if problems:
            raise run_stops.NeedsHuman("other", "Agent isolation is on but not effective: " + "; ".join(problems))
        log(f"Agent isolation: Agents run as {self.agent_user}; self-check passed")

    def isolation_self_check(self):
        return agent_process.run_isolation_probes(self.agent_user)

    def share_with_agent(self, path):
        if self.agent_user:
            sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{self.agent_user}:rwX,u:{os.environ.get('USER', 'runner')}:rwX", str(path)], check=False)

    def install_dependencies(self):
        if not (self.app_dir / "package-lock.json").exists():
            return
        began = time.time()
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR", "CI") if k in os.environ}
        try:
            code = sh(agent_process.agent_command(["npm", "ci", "--no-audit", "--no-fund"], env, self.agent_user), cwd=self.app_dir, env=env,
                      check=False, timeout=900).returncode
            self.share_with_agent(self.app_dir)
        except (subprocess.TimeoutExpired, OSError):
            code = "timeout"
        log(f"npm ci {'ok' if code == 0 else f'failed ({code}); the coder will install for itself'} in {time.time() - began:.0f}s")

    def check_daily_cap(self):
        cap = float(self.lim.get("daily_cost_cap_usd", 0) or 0)
        if cap <= 0:
            return
        total = spend_ledger.todays_spend(lambda args, tok: self.gh(args, token=tok, check=False), self.factory_repo, self.factory_token)
        if total is None:
            return
        self.state.d["daily_spent_usd"] = total
        if total >= cap:
            raise run_stops.NeedsHuman("other", f"today's Build Runs have already spent ${total:.2f} of the ${cap:.2f} daily cap; "
                                      "try again tomorrow or raise `limits.daily_cost_cap_usd`")

    def wait_for_capacity(self):
        cap = self.lim["max_simultaneous_build_runs"]
        give_up = time.time() + 30 * 60
        while True:
            out = self.gh(["run", "list", "--repo", self.factory_repo, "--workflow", "build-run.yml",
                           "--status", "in_progress", "--json", "databaseId"], token=self.factory_token).stdout
            others = [r for r in json.loads(out) if str(r["databaseId"]) != self.run_id]
            if len(others) < cap:
                return
            if time.time() > give_up:
                raise run_stops.NeedsHuman("other", f"{len(others)} other Build Run(s) in flight (cap {cap}) for 30 minutes")
            log(f"{len(others)} other Build Run(s) in flight (cap {cap}); waiting")
            time.sleep(60)

    def record_flag_in_manifest(self, slug):
        path = self.app_dir / "flags.json"
        before = path.read_text() if path.is_file() else ""
        description = getattr(self, "issue_title", "") or self.task.splitlines()[0]
        after = flag_slug.add_to_manifest(before, slug, f"{self.factory_repo}#{self.issue}", description)
        if after == before:
            return
        path.write_text(after)
        self.git("add", "--", "flags.json")
        self.git("-c", "user.name=ai-factory-orchestrator", "-c", "user.email=orchestrator@ai-factory.local", "commit", "-q", "-m", f"chore: record the flag {slug} for #{self.issue}")
        self.share_with_agent(self.app_dir)

    def name_the_flag(self):
        if flag_slug.SLOT not in (self.task or ""):
            return
        slug = flag_slug.for_story(self.issue)
        self.task = flag_slug.name_in(self.task, slug)
        if getattr(self, "spec", None):
            self.spec = flag_slug.name_in(self.spec, slug)
        self.state.d["flags"] = [slug]
        self.story_flags = [slug]
        self.state.d["named_flag"] = slug
        if flag_slug.ensure_feature(self.gb, self.app, slug, getattr(self, "issue_url", ""), getattr(self, "issue_title", ""), self.issue):
            self.state.d["created_flag"] = slug
        self.state.save()
        self.record_flag_in_manifest(slug)
