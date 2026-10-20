# STEP 4.1 and the setup before it: read the child, record the flag, wire the secrets, sync the Starter's protected files, pick the flags to retire,
# check the models, prepare the Agent account, install dependencies, and hold the daily cap and the capacity wait.
import json
import os
import re
import shutil
import subprocess
import time

from flag_lifecycle import (
    flag_manifest,
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
from try_fix import fix_request

from build_run import endings, read_child, verify_deployed_app

DEPLOY_WORKFLOW = ".github/workflows/deploy-fly.yml"


SECRETS_REGION_RE = re.compile(r"^([ \t]*)# factory-secrets:begin\n(?:.*\n)*?[ \t]*# factory-secrets:end$", re.M)


def wire_secrets(workflow_text, names):
    # The deploy workflow with each declared secret listed as an ordinary `NAME: ${{ secrets.NAME }}` line between its markers. Static
    # references, because a workflow that dumps the whole `secrets` context is flagged by GitHub as possibly malicious and never runs.
    names = sorted({n for n in names if isinstance(n, str) and not triage.secret_name_problem(n)})

    def region(m):
        indent = m.group(1)
        return "\n".join([f"{indent}# factory-secrets:begin"] + [f"{indent}{n}: ${{{{ secrets.{n} }}}}" for n in names] + [f"{indent}# factory-secrets:end"])
    return SECRETS_REGION_RE.sub(region, workflow_text, count=1)


class PrepareRun:
    def setup(self):
        out = self.gh(["issue", "view", self.issue, "--repo", self.factory_repo, "--json", "title,body,labels,comments"],
                      token=self.factory_token).stdout
        issue = json.loads(out)
        self.plan_meta = read_child.identify_intake(issue, self.app, self.issue)
        self.locate_plan()
        self.fix_meta = fix_request.fix_meta(issue["body"] or "")  # an older-style retry carried its state in the body
        # A story that failed before carries its retry state in a comment on this same issue: the attempt, its flag, what the earlier attempts
        # found and the guidance for this one. The same issue and the same flag run again.
        retry = fix_request.retry_state([c.get("body", "") for c in issue.get("comments") or []])
        self.retry_state = retry
        self.reuse_flags = [f for f in retry.get("flags", []) if isinstance(f, str) and flag_manifest.SLUG_RE.fullmatch(f)]
        if retry:
            self.fix_meta = {"origin": self.issue, "attempt": int(retry.get("attempt", 0)), "history": retry.get("history", [])}
        if self.fix_meta:
            self.state.d["fix"] = self.fix_meta
        self.task, self.cap = read_child.parse_intake(issue["body"] or "", self.lim["cost_cap_usd_default"],
                                           self.lim["cost_cap_usd_ceiling"])
        if retry.get("guidance"):
            self.task += "\n\n" + str(retry["guidance"])
        secrets = triage.find_secrets(issue["body"] or "")
        if secrets:
            raise endings.Refused(triage.secret_refusal(secrets))
        self.declared_secrets = secrets_marker.declared_secrets(issue)
        if self.declared_secrets:
            # Checked before the planner, the coder, the reviewer or the tester is paid for, on every start (a retry, a child, a re-run).
            self.require_secrets(self.declared_secrets)
            if self.plan_meta:
                self.task += secrets_check.secrets_note(self.declared_secrets)
        self.spec = self.task  # what the reviewer and tester check the work against; the planner may narrow it
        # The cap the issue asked for, if it asked for one, so child issues of a plan keep it instead of the default.
        raw_cap = read_form.form_section(issue["body"] or "", "Cost cap override (USD)").lstrip("$")
        self.cap_override = raw_cap if raw_cap and raw_cap != "_No response_" else None
        self.issue_title = issue.get("title", "")
        self.state.d["cap_usd"] = self.cap
        self.state.d["context_goal_tokens"] = self.lim.get("context_goal_tokens", 100000)
        self.state.save()
        self.check_daily_cap()
        self.prepare_agent_user()
        self.check_models()
        self.wait_for_capacity()
        self.meter = spend_budget.Budget(os.environ["DEEPINFRA_API_KEY"], self.cap, self.lim["jwt_ttl_seconds"])
        self.make_runner()
        self.preview = preview_token.for_app(os.environ["PREVIEW_MASTER_SECRET"], self.app)
        print(f"::add-mask::{self.preview}", flush=True)
        # Clone with the PAT passed per command only, so the checkout stores no credential
        # and the coder (who runs in it) cannot push or read one.
        sh(["git", "clone", "-q", f"https://github.com/{self.app_repo}.git", str(self.app_dir)],
           env={**os.environ, **github.git_auth_env(self.auth_header)})
        self.share_with_agent(self.app_dir)
        self.install_dependencies()
        self.git("config", "user.name", "ai-factory-coder")
        self.git("config", "user.email", "coder@ai-factory.local")
        labels = {l["name"] for l in issue.get("labels", [])}
        self.apply_template_files(labels)
        self.state.d["base_sha"] = self.head()
        self.stage_template_config(labels)
        self.state.d["build_kind"] = self.build_kind
        self.retiring = self.choose_flags_to_retire()
        self.state.save()
        log(f"Intake #{self.issue}: app {self.app}, cap ${self.cap:.2f}, base {self.state.d['base_sha'][:8]}")

    def locate_plan(self):
        # The plan this child belongs to, from the sub-issues API (not a label or the title): only the parent's number and state are read, never its
        # body. A child must carry a marker and be a sub-issue of the open plan the marker names, or it is refused as not planned yet.
        found = child_tickets.parent_info(self.factory_repo, self.issue, self.factory_token, lambda args, token: self.gh(args, token=token, check=False))
        read_child.require_planned(self.issue, self.plan_meta, found)
        self.parent = found["number"]
        self.state.d["parent"] = self.parent

    def require_secrets(self, needed, record=False):
        # Stop (AwaitingSecret) until every secret declared for this request exists as a GitHub Actions secret on the app's repository. The planning
        # process made the first check and left the declared names in a marker; this check runs again at the start of every Build Run, before any
        # Agent is paid for (a retry, a child, a re-run). `record` also comments the request on the Intake; nothing here reads a value.
        try:
            have = secrets_check.present_names(lambda args: self.gh(args, check=False), self.app_repo)
        except secrets_check.SecretsUnreadable as e:
            raise run_stops.NeedsHuman("other", str(e))
        self.state.d["secrets"] = [x["name"] for x in needed]
        missing = secrets_check.missing_secrets(needed, have)
        if record:
            self.gh(["issue", "comment", str(self.issue), "--repo", self.factory_repo, "--body", secrets_check.request_comment(needed, missing, self.app_repo)],
                    token=self.factory_token, check=False)
        if missing:
            raise endings.AwaitingSecret(secrets_check.waiting_message(missing, self.app_repo, "add `proceed-with-change` again"))

    def copy_template_files(self, group):
        # Copy the Starter Template files in `group` that differ into the app checkout and commit them locally. Returns the paths changed.
        changed = []
        for rel in group:
            src, dst = config.FACTORY_DIR / "templates" / "starter" / rel, self.app_dir / rel
            if not src.is_file():
                continue
            wanted = src.read_bytes()
            if rel == DEPLOY_WORKFLOW:  # the app's declared secrets stay listed in the workflow when the template is copied over it
                wanted = wire_secrets(wanted.decode(), self.secret_names()).encode()
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

    def secret_names(self):
        # The secret names this app declares: in its committed `secrets.json`, and the plan's declared ones for this run.
        names = list(self.state.d.get("secrets") or [])
        try:
            names += [x.get("name") for x in json.loads((self.app_dir / "secrets.json").read_text()).get("secrets", [])]
        except (OSError, ValueError, AttributeError):
            pass
        return names

    def stage_secret_wiring(self):
        # List the run's declared secrets in the deploy workflow (an Orchestrator-owned file), committed locally and pushed with the coder's
        # reviewed work, like the lint config. Before the coder starts, so its protected-file check starts from this commit.
        if not self.state.d.get("secrets"):
            return
        try:
            if self.copy_template_files((DEPLOY_WORKFLOW,)):
                log("listed the declared secrets in the deploy workflow: " + ", ".join(self.state.d["secrets"]))
        except Exception as e:  # noqa: BLE001
            log(f"could not list the secrets in the deploy workflow: {type(e).__name__}: {e}")

    def apply_template_files(self, labels):
        # A template-sync Intake: copy the protected Starter Template files in TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR into the app and
        # push them before the planner and coder start, so the run's starting point already has them. No Agent touches them. A failure is
        # logged and the run goes on: the rest of the sync does not depend on these files.
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
        # The lint and formatter config (TEMPLATE_FILES_HELD) is committed locally, after the run's base, and goes out with the coder's first
        # reviewed push: on its own it could turn the app's Test Gate red, and the coder, only the coder, fixes what the new rules report.
        if "template-sync" not in labels:
            return
        try:
            changed = self.copy_template_files(starter_template.TEMPLATE_FILES_HELD)
            if changed:
                log("staged protected lint config, pushed with the coder's work: " + ", ".join(changed))
        except Exception as e:  # noqa: BLE001
            log(f"could not stage the lint config: {type(e).__name__}: {e}")

    def choose_flags_to_retire(self):
        # The proven flags that ride along with this run (flag_lifecycle/retirement_selection.py).
        picked, issues = retirement_selection.choose(
            not self.fix_meta and self.build_kind == "update", self.task, self.app_repo.split("/")[0], self.app,
            self.pat, self.lim.get("flag_retirement") or {}, self.git("show", "HEAD:flags.json", check=False).stdout,
            time.strftime("%Y-%m-%d", time.gmtime()))
        if issues:
            self.flag_issues = issues
        return picked

    def check_models(self):
        # Before any work: a one-token request per distinct model this run will use. A model the provider no longer serves is replaced by the role's
        # `fallback_model` for this run (recorded in the Report), or stops the run with the reason if there is none, instead of failing after a clone,
        # a checkout and a planner call. Models get cheaper and are retired; this is how an unattended night survives a retirement. A balance of zero
        # raises ProviderBlocked as before.
        base, key = self.cfg["provider"]["base_url"], os.environ["DEEPINFRA_API_KEY"]
        seen, swapped = {}, {}

        def status(model):
            if model not in seen:
                seen[model] = provider.model_status(base, key, model)
            return seen[model]

        for role in ["coder", "tester", "reviewer"]:
            profile = self.cfg["roles"].get(role)
            if not profile:
                continue
            model = profile["model"]
            if status(model) != "missing":
                continue
            fallback = profile.get("fallback_model")
            if not fallback or status(fallback) == "missing":
                raise run_stops.NeedsHuman("other", f"the {role} model `{model}` is no longer served by the provider and "
                                          + (f"its fallback `{fallback}` is not either" if fallback else "the role has no `fallback_model`")
                                          + ": choose a model in agents/profiles.yml")
            profile["model"] = fallback
            swapped[role] = {"from": model, "to": fallback}
            log(f"{role}: `{model}` is not served by the provider; using its fallback `{fallback}` for this run")
        if swapped:
            self.state.d["fallbacks"] = swapped
            self.state.save()

    def prepare_agent_user(self):
        # With isolation on: put the helper the tester calls where the Agent user can read it, and prove isolation holds before
        # any Agent runs. A run that cannot prove it stops, because an Agent next to the Orchestrator's secrets is what this prevents.
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
        # Make `path` readable and writable by both the Agent user and this process (what was just cloned or installed was created
        # by one of them). No-op without isolation.
        if self.agent_user:
            sh(["sudo", "-n", "setfacl", "-R", "-m", f"u:{self.agent_user}:rwX,u:{os.environ.get('USER', 'runner')}:rwX", str(path)], check=False)

    def install_dependencies(self):
        # Install once, here, so the coder starts with node_modules instead of spending agent turns on it.
        # Later rounds reuse the checkout, and restore_tree/clean leave ignored node_modules alone. Runs with
        # the coder's minimal environment, so the dependencies' install scripts never see the runner's secrets.
        # A failure is only logged: the coder can still install for itself.
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

    def ledger_issue(self):
        # The number of the open spend-ledger issue in ai-factory, or None before the first run has made one.
        out = self.gh(["issue", "list", "--repo", self.factory_repo, "--label", spend_ledger.LEDGER_LABEL, "--state", "open",
                       "--json", "number"], token=self.factory_token, check=False).stdout
        found = json.loads(out or "[]")
        return found[0]["number"] if found else None

    def check_daily_cap(self):
        # Refuse to start a Build Run once today's finished runs have spent `daily_cost_cap_usd`. Runs still
        # in flight are not counted until they finish, so concurrent runs can overshoot by their own caps.
        cap = float(self.lim.get("daily_cost_cap_usd", 0) or 0)
        if cap <= 0:
            return
        number = self.ledger_issue()
        if not number:
            return
        day = time.strftime("%Y-%m-%d", time.gmtime())
        out = self.gh(["api", f"repos/{self.factory_repo}/issues/{number}/comments?per_page=100&since={day}T00:00:00Z",
                       "--paginate", "--jq", ".[].body"], token=self.factory_token, check=False).stdout
        total = spend_ledger.ledger_total(out.split("\n"), day)
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

    def name_the_flag(self):
        # A flagged change set's task carries a placeholder for the flag's slug (flag_lifecycle/flag_slug.py). Fill it with the story's flag: a
        # retried story keeps the flag it had, any other is `issue-<n>` of this issue. Create the GrowthBook feature (production off) and record
        # the flag in `flags.json` before the coder starts, so the coder only wraps code; the flag exists while it and the tester work.
        if flag_slug.SLOT not in (self.task or ""):
            return
        # A fix child names the failed story's flag (`flag_story` in its marker); any other child, its own number.
        slug = self.reuse_flags[0] if self.reuse_flags else flag_slug.for_story(child_tickets.story_number(getattr(self, "plan_meta", None) or {}, self.issue))
        self.task = flag_slug.name_in(self.task, slug)
        if getattr(self, "spec", None):
            self.spec = flag_slug.name_in(self.spec, slug)
        self.state.d["flags"] = [slug]
        self.story_flags = [slug]
        self.state.d["named_flag"] = slug
        if flag_slug.ensure_feature(self.gb, self.app, slug, getattr(self, "issue_url", ""), getattr(self, "issue_title", ""), self.issue):
            self.state.d["created_flag"] = slug
        self.state.save()
        path = self.app_dir / "flags.json"
        before = path.read_text() if path.is_file() else ""
        after = flag_slug.add_to_manifest(before, slug, f"{self.factory_repo}#{self.issue}", getattr(self, "issue_title", "") or self.task.splitlines()[0])
        if after != before:
            path.write_text(after)
            self.git("add", "--", "flags.json")
            self.git("-c", "user.name=ai-factory-orchestrator", "-c", "user.email=orchestrator@ai-factory.local", "commit", "-q", "-m",
                     f"chore: record the flag {slug} for #{self.issue}")
            self.share_with_agent(self.app_dir)
