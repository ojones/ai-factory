#!/usr/bin/env python3
"""Build Run orchestrator (ARCHITECTURE.md → Agents and Build Run stages).

Two subcommands, both run by .github/workflows/build-run.yml:

  run       coder → CI/deploy dark → reviewer + tester → fix loop → release
  finalize  always runs last: renders the Summary, Report and failure Issue
            from run/state.json, which `run` updates after every stage, so a
            crash, breach or killed job still reports.

Agents are OpenHands subprocesses with a whitelisted environment. They never
hold the PAT, the GrowthBook admin key, the Fly token or the DeepInfra parent
key; the coder only commits, and this process pushes.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import threading
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FACTORY_DIR = Path(__file__).resolve().parent.parent
DEEPINFRA = "https://api.deepinfra.com"
GROWTHBOOK_API = os.environ.get("GROWTHBOOK_API_HOST", "https://ai-factory-growthbook.fly.dev:3100") + "/api/v1"
PIPELINE = [("Test Gate", "test-gate.yml"), ("Build", "build.yml"), ("Deploy to Fly", "deploy-fly.yml")]
# Starter Template files the coder must not change: the workflows hold the Fly
# token, and the flag wrapper is the release gate's other half.
PROTECTED = (".github/", "fly.toml", "fly/", "backend/src/feature-flags.ts", "INTAKE.md")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class BudgetExhausted(Exception):
    pass


class NeedsHuman(Exception):
    """kind: round_limit | time_limit | pipeline | other"""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


# --- pure logic (unit-tested) -------------------------------------------------


def form_section(body, heading):
    """Text under `### <heading>` in an Issue Form body, surrounding blanks trimmed."""
    out, on = [], False
    for line in body.replace("\r", "").split("\n"):
        if line == f"### {heading}":
            on = True
        elif line.startswith("### "):
            on = False
        elif on:
            out.append(line)
    return "\n".join(out).strip()


def parse_intake(body, default_cap, ceiling):
    task = form_section(body, "What should be built?")
    if not task or task == "_No response_":
        raise NeedsHuman("other", "The Intake's \"What should be built?\" field is empty.")
    raw = form_section(body, "Cost cap override (USD)").lstrip("$")
    if not raw or raw == "_No response_":
        return task, float(default_cap)
    try:
        cap = float(raw)
    except ValueError:
        raise NeedsHuman("other", f"Cost cap override {raw!r} is not a number.")
    if not 0 < cap <= float(ceiling):
        raise NeedsHuman("other", f"Cost cap override ${cap} must be > 0 and <= the ${ceiling} ceiling.")
    return task, cap


def derive_review(doc):
    """(clean, blocking, minor). The verdict comes from the findings, never the model's own field."""
    findings = doc.get("findings") if isinstance(doc, dict) else None
    if not isinstance(findings, list):
        raise ValueError("reviewer output has no findings list")
    blocking = [f for f in findings if isinstance(f, dict) and f.get("severity") == "blocking"]
    minor = [f for f in findings if isinstance(f, dict) and f.get("severity") != "blocking"]
    return not blocking, blocking, minor


def derive_test(doc, expected_flags):
    """(passed, failures). passed is derived from the results, and every new flag needs a result."""
    results = doc.get("results") if isinstance(doc, dict) else None
    if not isinstance(results, list):
        raise ValueError("tester output has no results list")
    failures = [r for r in results if not (isinstance(r, dict) and r.get("passed") is True)]
    covered = {r.get("flag") for r in results if isinstance(r, dict)}
    for slug in expected_flags:
        if slug not in covered:
            failures.append({"flag": slug, "check": "coverage", "passed": False,
                             "evidence": "the tester recorded no result for this flag"})
    return not failures, failures


def new_flag_slugs(base_json, head_json):
    def slugs(text):
        try:
            return [e["slug"] for e in json.loads(text) if isinstance(e, dict) and "slug" in e]
        except (ValueError, TypeError):
            return []
    base = set(slugs(base_json))
    return [s for s in slugs(head_json) if s not in base]


def protected_violations(changed_files):
    return [f for f in changed_files if f.startswith(PROTECTED) or f in PROTECTED]


def release_gate(ci_green, deploy_healthy, tester_passed, reviewer_clean, reviewed_sha, head_sha):
    """Release only when all four hold for the pushed SHA."""
    return all([ci_green, deploy_healthy, tester_passed, reviewer_clean]) and reviewed_sha == head_sha


def preview_token(master_secret, slug):
    """Same derivation as infra/app-staging/preview-token.sh."""
    return hmac.new(master_secret.encode(), slug.encode(), hashlib.sha256).hexdigest()


def summarize_token_usage(base_state):
    """Per-invocation context stats from OpenHands' persisted base_state.json.

    prompt_tokens of one LLM call is that call's context size, so the max over calls is the
    invocation's peak context. The condenser's own calls are counted separately.
    """
    metrics = (base_state.get("stats") or {}).get("usage_to_metrics") or {}
    agent = (metrics.get("agent") or {}).get("token_usages") or []
    condenser = (metrics.get("condenser") or {}).get("token_usages") or []
    prompts = [u.get("prompt_tokens", 0) for u in agent]
    return {"calls": len(agent), "condenser_calls": len(condenser),
            "peak_context": max(prompts, default=0), "last_context": prompts[-1] if prompts else 0,
            "prompt_tokens": sum(prompts), "completion_tokens": sum(u.get("completion_tokens", 0) for u in agent),
            "cache_read_tokens": sum(u.get("cache_read_tokens", 0) for u in agent)}


def merge_usage(a, b):
    """Combine two invocations' stats (a retry of the same role)."""
    if not a:
        return b
    if not b:
        return a
    out = {k: a[k] + b[k] for k in a if k not in ("peak_context", "last_context")}
    out["peak_context"] = max(a["peak_context"], b["peak_context"])
    out["last_context"] = b["last_context"]
    return out


def render(template, values):
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    left = re.findall(r"\{\{\w+\}\}", out)
    if left:
        raise ValueError(f"unreplaced prompt placeholders: {left}")
    return out


# --- plumbing -----------------------------------------------------------------


def log(msg):
    print(msg, flush=True)


def sh(cmd, cwd=None, env=None, check=True, timeout=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}... failed ({p.returncode}): {(p.stderr or p.stdout)[-600:]}")
    return p


def http(method, url, token=None, body=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, (json.loads(raw) if raw else {})
            except ValueError:
                return r.status, raw[:500].decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500].decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def load_config():
    import yaml
    return yaml.safe_load((FACTORY_DIR / "agents" / "profiles.yml").read_text())


class Budget:
    """The run's one cap, enforced and metered by DeepInfra scoped JWTs.

    A spending-limited JWT can carry only one model, so each Agent invocation gets its own
    single-model JWT limited to what is left of the run's cap. DeepInfra refuses the first call
    after a JWT's limit (403) and the crossing call completes. The run's spend is the sum of every
    JWT's spending_current, so there are still no per-Agent budgets.
    """

    def __init__(self, admin_key, cap, ttl):
        self.admin_key, self.cap, self.ttl = admin_key, cap, ttl
        self.tokens = {}  # jwt -> last read spending_current

    def mint(self, model, share=1.0):
        """`share` < 1 splits what is left between invocations that run at the same time, so
        together they cannot spend past the cap."""
        remaining = round((self.cap - self.spent_known()) * share, 6)
        if remaining <= 0:
            raise BudgetExhausted(f"${self.spent_known():.4f} spent against a ${self.cap:.2f} cap")
        status, r = http("POST", f"{DEEPINFRA}/v1/scoped-jwt", self.admin_key,
                         {"api_key_name": "auto", "models": [model], "expires_delta": self.ttl, "spending_limit": remaining})
        if status != 200 or "token" not in r:
            raise RuntimeError(f"could not mint scoped JWT: HTTP {status} {r}")
        print(f"::add-mask::{r['token']}", flush=True)
        self.tokens[r["token"]] = 0.0
        return r["token"]

    def spent_known(self):
        return sum(self.tokens.values())

    def refresh(self, jwt):
        status, r = http("GET", f"{DEEPINFRA}/v1/scoped-jwt?jwtoken={jwt}", self.admin_key)
        if status != 200:
            raise RuntimeError(f"could not read JWT spend: HTTP {status}")
        self.tokens[jwt] = float(r["spending_current"])
        return self.spent_known()


class State:
    def __init__(self, path, app, issue, run_url):
        self.path = Path(path)
        self.d = {"app": app, "issue_number": issue, "run_url": run_url, "outcome": "running", "message": "",
                  "cap_usd": None, "spent_usd": 0.0, "base_sha": None, "head_sha": None, "review_passes": 0,
                  "commits": [], "stages": [], "release": None, "blocking": [],
                  "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=2))
        tmp.replace(self.path)

    def stage(self, name, agent, rnd, cost, verdict, usage=None):
        self.d["stages"].append({"stage": name, "agent": agent, "round": rnd,
                                 "cost_usd": round(cost, 6), "verdict": verdict, "usage": usage})
        self.save()
        return self.d["stages"][-1]


# --- the Build Run ------------------------------------------------------------


class BuildRun:
    def __init__(self):
        e = os.environ
        self.app = e["APP_NAME"]
        self.issue = e["ISSUE_NUMBER"]
        if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", self.app) or len(self.app) > 30 or not self.issue.isdigit():
            raise SystemExit(f"invalid inputs: app_name={self.app!r} issue_number={self.issue!r}")
        self.factory_repo = e["GITHUB_REPOSITORY"]
        self.owner = self.factory_repo.split("/")[0]
        self.app_repo = f"{self.owner}/{self.app}"
        self.run_id = e.get("GITHUB_RUN_ID", "0")
        self.run_url = f"{e.get('GITHUB_SERVER_URL', 'https://github.com')}/{self.factory_repo}/actions/runs/{self.run_id}"
        self.pat = e["FACTORY_PAT"]
        self.factory_token = e["FACTORY_GH_TOKEN"]
        self.work = Path(e["BUILD_RUN_DIR"])
        self.app_dir = Path(e["APP_DIR"])
        self.art = self.work / "artifacts"
        self.art.mkdir(parents=True, exist_ok=True)
        self.cfg = load_config()
        self.lim = self.cfg["limits"]
        self.state = State(self.work / "state.json", self.app, self.issue, self.run_url)
        self.start = time.time()
        self.deadline = self.start + self.lim["time_limit_minutes"] * 60
        self.cap = None
        self.meter = None
        self._usage = None
        self.lock = threading.Lock()  # guards the meter, the state and log output across parallel Agents
        self.preview = None
        self.auth_header = "Authorization: Basic " + base64.b64encode(
            f"x-access-token:{self.pat}".encode()).decode()
        print(f"::add-mask::{self.auth_header.split()[-1]}", flush=True)

    # --- gh / git

    def gh(self, args, token=None, check=True):
        return sh(["gh", *args], env={**os.environ, "GH_TOKEN": token or self.pat}, check=check)

    def git(self, *args, check=True, cwd=None):
        return sh(["git", *args], cwd=cwd or self.app_dir, check=check)

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()

    # --- limits

    def check_limits(self):
        if self.meter and self.cap is not None and self.state.d["spent_usd"] >= self.cap:
            raise BudgetExhausted(f"${self.state.d['spent_usd']:.4f} spent against a ${self.cap:.2f} cap")
        if time.time() > self.deadline:
            raise NeedsHuman("time_limit", f"the {self.lim['time_limit_minutes']}-minute time limit was reached")

    def record_spend(self, jwt):
        with self.lock:
            self.state.d["spent_usd"] = round(self.meter.refresh(jwt), 6)
            self.state.save()
            return self.state.d["spent_usd"]

    # --- setup

    def setup(self):
        out = self.gh(["issue", "view", self.issue, "--repo", self.factory_repo, "--json", "title,body"],
                      token=self.factory_token).stdout
        issue = json.loads(out)
        if issue["title"].strip() != self.app:
            raise NeedsHuman("other", f"Intake #{self.issue} is titled {issue['title']!r}, not {self.app!r}.")
        self.task, self.cap = parse_intake(issue["body"] or "", self.lim["cost_cap_usd_default"],
                                           self.lim["cost_cap_usd_ceiling"])
        self.state.d["cap_usd"] = self.cap
        self.state.d["context_goal_tokens"] = self.lim.get("context_goal_tokens", 100000)
        self.state.save()
        self.wait_for_capacity()
        self.meter = Budget(os.environ["DEEPINFRA_API_KEY"], self.cap, self.lim["jwt_ttl_seconds"])
        self.preview = preview_token(os.environ["PREVIEW_MASTER_SECRET"], self.app)
        print(f"::add-mask::{self.preview}", flush=True)
        # Clone with the PAT passed per command only, so the checkout stores no credential
        # and the coder (who runs in it) cannot push or read one.
        sh(["git", "-c", f"http.extraheader={self.auth_header}", "clone", "-q",
            f"https://github.com/{self.app_repo}.git", str(self.app_dir)])
        self.git("config", "user.name", "ai-factory-coder")
        self.git("config", "user.email", "coder@ai-factory.local")
        self.state.d["base_sha"] = self.head()
        self.state.save()
        log(f"Intake #{self.issue}: app {self.app}, cap ${self.cap:.2f}, base {self.state.d['base_sha'][:8]}")

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
                raise NeedsHuman("other", f"{len(others)} other Build Run(s) in flight (cap {cap}) for 30 minutes")
            log(f"{len(others)} other Build Run(s) in flight (cap {cap}); waiting")
            time.sleep(60)

    # --- agents

    def agent_env(self, role, jwt, extra=None, home=None):
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR", "CI") if k in os.environ}
        if home:
            env["HOME"] = str(home)
        profile = self.cfg["roles"][role]
        env.update({"LLM_MODEL": "openai/" + profile["model"], "LLM_BASE_URL": self.cfg["provider"]["base_url"],
                    "LLM_API_KEY": jwt, "RUNTIME": "process"})
        env.update(extra or {})
        return env

    def invoke(self, role, label, values, extra_env=None, cwd=None, home=None, share=1.0):
        """One headless OpenHands invocation. Safe to call from several threads at once when each
        has its own `home` (OpenHands keeps its conversations there) and `cwd`.
        Returns (exit status, 'timeout' if killed; cost; token usage)."""
        self.check_limits()
        template = (FACTORY_DIR / "agents" / self.cfg["roles"][role]["prompt"]).read_text()
        prompt = render(template, {"app_name": self.app, **values})
        with self.lock:
            before = self.state.d["spent_usd"]
            jwt = self.meter.mint(self.cfg["roles"][role]["model"], share)
        if home:
            Path(home).mkdir(parents=True, exist_ok=True)
        jsonl = self.art / f"openhands-{role}-{label}.jsonl"
        known = self.conversation_dirs(home)
        try:
            with jsonl.open("w") as f:
                rc = subprocess.run(["openhands", "--headless", "--override-with-envs", "--json", "-t", prompt],
                                    cwd=cwd or self.app_dir, env=self.agent_env(role, jwt, extra_env, home), stdout=f,
                                    stderr=subprocess.STDOUT, timeout=self.lim["agent_timeout_minutes"] * 60).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
        after = self.record_spend(jwt)
        usage = self.collect_usage(role, label, known, home)
        # Spend is read from the shared total, so with two Agents running its delta would include
        # the other's; the JWT's own spend is this invocation's exact cost.
        cost = self.meter.tokens[jwt]
        lines = [f"::group::{role} ({label})",
                 f"{role} ({label}) exited {rc}; cost ${cost:.4f}; run total ${after:.4f} of ${self.cap:.2f}", "::endgroup::"]
        if usage:
            goal = self.lim.get("context_goal_tokens", 100000)
            lines.insert(2, f"{role} ({label}) context: {usage['calls']} calls, peak {usage['peak_context']:,} tokens"
                         + (f" (over the {goal:,} goal)" if usage["peak_context"] > goal else ""))
        with self.lock:  # one block, so parallel Agents' groups do not interleave
            for line in lines:
                log(line)
        return rc, cost, usage

    def run_agent(self, role, label, values, extra_env=None):
        """The sequential form: records cost and usage on the Build Run for the caller to read."""
        rc, self._last_cost, usage = self.invoke(role, label, values, extra_env)
        self._usage = merge_usage(self._usage, usage)
        return rc

    def conversations_root(self, home=None):
        return Path(home or os.environ.get("HOME", "~")).expanduser() / ".openhands" / "conversations"

    def conversation_dirs(self, home=None):
        root = self.conversations_root(home)
        return {p.name for p in root.iterdir()} if root.is_dir() else set()

    def collect_usage(self, role, label, known, home=None):
        """Read the conversation this invocation created and keep its raw state as an artifact."""
        root = self.conversations_root(home)
        for name in sorted(self.conversation_dirs(home) - known):
            src = root / name / "base_state.json"
            doc = load_json(src)
            if doc is not None:
                (self.art / f"openhands-{role}-{label}-state.json").write_text(src.read_text())
                return summarize_token_usage(doc)
        return None

    def take_usage(self):
        usage, self._usage = self._usage, None
        return usage

    def agent_json(self, role, label, values, path, extra_env=None, check=None, cwd=None, home=None, share=1.0):
        """Run a role that writes a JSON file; one retry if the file is missing or malformed.
        Returns (document, cost, token usage)."""
        total_cost, usage = 0.0, None
        for attempt in (1, 2):
            Path(path).unlink(missing_ok=True)
            _, cost, used = self.invoke(role, f"{label}{'' if attempt == 1 else 'b'}", values, extra_env, cwd, home, share)
            total_cost += cost
            usage = merge_usage(usage, used)
            doc = load_json(path)
            try:
                if doc is not None and (check is None or check(doc) is not False):
                    return doc, total_cost, usage
            except (ValueError, AttributeError, TypeError):
                pass
            self.restore_tree(cwd)
        raise NeedsHuman("other", f"the {role} produced no valid output file twice")

    def restore_tree(self, cwd=None):
        """Read-only roles must leave the tree untouched; undo it if they did not."""
        if self.git("status", "--porcelain", cwd=cwd).stdout.strip():
            log("A read-only Agent modified the working tree; restoring it.")
            self.git("reset", "-q", "--hard", "HEAD", cwd=cwd)
            self.git("clean", "-fdq", cwd=cwd)

    # --- coder + push

    def coder(self, label, task, findings_path):
        task0, attempts = task, 0
        base = self.head()
        while True:
            self.run_agent("coder", label, {"round": label, "task": task, "findings_path": findings_path})
            cost, head = self._last_cost, self.head()
            problem = None
            if head == base:
                problem = "You made no commit. Make the change, then run `git add` and `git commit`."
            elif self.git("merge-base", "--is-ancestor", base, head, check=False).returncode != 0:
                self.git("reset", "-q", "--hard", base)
                problem = "You rewrote history. Add new commits on top of the existing ones only."
            else:
                changed = self.git("diff", "--name-only", f"{base}..{head}").stdout.split("\n")
                bad = protected_violations([c for c in changed if c])
                if bad:
                    self.git("reset", "-q", "--hard", base)
                    problem = f"Your commits changed protected Starter Template files ({', '.join(bad)}). They were discarded. Redo the work without touching them."
            if problem:
                attempts += 1
                self.state.stage("Coder", "coder", label, cost, f"rejected: {problem[:60]}", self.take_usage())
                if attempts >= 3:
                    raise NeedsHuman("other", f"the coder could not produce an acceptable commit: {problem}")
                task = f"{problem}\n\nOriginal task:\n{task0}"
                continue
            self.check_limits()
            sh(["git", "-c", f"http.extraheader={self.auth_header}", "push", "-q", "origin", "HEAD:main"],
               cwd=self.app_dir)
            self.state.d["head_sha"] = head
            self.state.d["commits"].append(head)
            self.state.stage("Coder", "coder", label, cost, f"pushed {head[:8]}", self.take_usage())
            return head

    # --- CI / deploy

    def wait_run(self, workflow, sha):
        give_up = time.time() + self.lim["pipeline_timeout_minutes"] * 60
        while time.time() < give_up:
            self.check_limits()
            out = self.gh(["run", "list", "--repo", self.app_repo, "--workflow", workflow, "--limit", "30",
                           "--json", "databaseId,headSha,status,conclusion,url"]).stdout
            runs = sorted((r for r in json.loads(out) if r["headSha"] == sha), key=lambda r: r["databaseId"])
            if runs and runs[-1]["status"] == "completed":
                return runs[-1]
            time.sleep(10)
        raise NeedsHuman("pipeline", f"{workflow} did not finish for {sha[:8]} within {self.lim['pipeline_timeout_minutes']} minutes")

    def healthy(self):
        for _ in range(12):
            status, body = http("GET", f"https://{self.app}.fly.dev/api/health", timeout=20)
            if status == 200:
                return True
            time.sleep(5)
        return False

    def failure_context(self, failed, sha, n):
        ctx = self.work / f"context-{n}"
        ctx.mkdir(parents=True, exist_ok=True)
        name, run = failed
        if run:
            p = self.gh(["run", "view", str(run["databaseId"]), "--repo", self.app_repo, "--log-failed"], check=False)
            (ctx / "failed-run.log").write_text((p.stdout or p.stderr)[-30000:])
        fly_env = {**os.environ, "FLY_API_TOKEN": os.environ.get("FLY_API_TOKEN", "")}
        for fname, args in (("fly-status.txt", ["status"]), ("fly-logs.txt", ["logs", "--no-tail"])):
            try:
                p = sh(["flyctl", *args, "--app", self.app], env=fly_env, check=False, timeout=120)
                text = p.stdout or p.stderr
            except (OSError, subprocess.TimeoutExpired) as e:
                text = f"flyctl unavailable: {e}"
            (ctx / fname).write_text(text[-15000:])
        return ctx

    def pipeline(self, sha):
        """Wait for Test Gate → Build → Deploy on sha, handling failures; returns the final green SHA."""
        retries, fixes, n = self.lim["pipeline_retries"], 0, 0
        while True:
            failed = None
            for name, wf in PIPELINE:
                run = self.wait_run(wf, sha)
                if run["conclusion"] != "success":
                    failed = (name, run)
                    break
            if failed is None and not self.healthy():
                failed = ("Health check", None)
            if failed is None:
                self.state.stage("CI / Build / Deploy", "-", "-", 0, f"green, deployed dark {sha[:8]}")
                return sha
            n += 1
            ctx = self.failure_context(failed, sha, n)
            url = failed[1]["url"] if failed[1] else f"https://github.com/{self.app_repo}/actions"
            diag, cost, usage = self.agent_json(
                "pipeline", f"p{n}", {"head_sha": sha, "failure_run_url": url, "context_dir": ctx,
                                      "diagnosis_path": self.work / f"diagnosis-{n}.json"},
                self.work / f"diagnosis-{n}.json", check=lambda d: d.get("category") in ("code", "workflow", "infra", "flaky"))
            diag = load_json(self.work / f"diagnosis-{n}.json")
            self.state.stage(f"{failed[0]} failed", "pipeline", n, cost, diag["category"], usage)
            cat = diag["category"]
            if cat in ("flaky", "infra") and diag.get("retry_recommended") and retries > 0:
                retries -= 1
                if failed[1]:
                    self.gh(["run", "rerun", str(failed[1]["databaseId"]), "--repo", self.app_repo, "--failed"], check=False)
                time.sleep(20)
                continue
            if cat == "code" and diag.get("fix_request") and fixes < self.lim["pipeline_fix_attempts"]:
                fixes += 1
                sha = self.coder(f"fix{fixes}", diag["fix_request"], str(self.work / "findings-none.json"))
                continue
            raise NeedsHuman("pipeline", f"{failed[0]} failed ({cat}): {diag.get('summary', '')[:500]}")

    # --- review + test

    def review_and_test(self, base, head, rnd):
        """The reviewer reads the code and the tester drives the deployed app; neither needs the
        other's result, so they run at the same time. Each gets half of what is left of the
        budget, its own HOME (OpenHands keeps its conversations there) and, for the tester, its
        own checkout of `head`."""
        d = self.state.d
        d["review_passes"] = rnd
        self.restore_tree()
        base_flags = self.git("show", f"{base}:flags.json", check=False).stdout
        head_flags = self.git("show", f"{head}:flags.json", check=False).stdout
        flags = new_flag_slugs(base_flags, head_flags)
        share = 0.5 if flags else 1.0
        tester_tree = self.work / f"tester-tree-{rnd}"

        def review():
            return self.agent_json(
                "reviewer", f"r{rnd}", {"base_sha": base, "head_sha": head, "verdict_path": self.work / f"verdict-{rnd}.json"},
                self.work / f"verdict-{rnd}.json", check=lambda doc: derive_review(doc) and None,
                home=self.work / f"home-reviewer-{rnd}", share=share)

        def test():
            self.git("worktree", "add", "--detach", str(tester_tree), head)
            try:
                return self.agent_json(
                    "tester", f"t{rnd}", {"app_url": f"https://{self.app}.fly.dev", "head_sha": head,
                                          "report_path": self.work / f"test-report-{rnd}.json"},
                    self.work / f"test-report-{rnd}.json", {"PREVIEW_TOKEN": self.preview},
                    check=lambda doc: derive_test(doc, flags) and None,
                    cwd=tester_tree, home=self.work / f"home-tester-{rnd}", share=share)
            finally:
                self.git("worktree", "remove", "--force", str(tester_tree), check=False)

        with ThreadPoolExecutor(max_workers=2) as pool:
            review_job = pool.submit(review)
            test_job = pool.submit(test) if flags else None
        # The pool has waited for both. Collect the reviewer first, then the tester, so a failure
        # in one still lets the other's cost reach the state.
        errors = []
        try:
            reviewer_doc, cost, usage = review_job.result()
            self.restore_tree()
            clean, blocking, minor = derive_review(reviewer_doc)
            self.state.stage("Review", "reviewer", rnd, cost, "clean" if clean else f"{len(blocking)} blocking", usage)
        except Exception as e:  # noqa: BLE001 - re-raised below, after the tester is recorded
            errors.append(e)
        test_failures, tpassed = [], True
        if test_job is None:
            self.state.stage("Test", "tester", rnd, 0, "skipped: no new flags")
        else:
            try:
                tdoc, cost, usage = test_job.result()
                tpassed, test_failures = derive_test(tdoc, flags)
                self.state.stage("Test", "tester", rnd, cost, "passed" if tpassed else f"{len(test_failures)} failed", usage)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        if errors:
            raise errors[0]
        all_blocking = (
            [{"source": "reviewer", "summary": f.get("summary", ""), "evidence": f.get("evidence", "")} for f in blocking]
            + [{"source": "tester", "summary": f"{r.get('flag')}: {r.get('check')}", "evidence": r.get("evidence", "")}
               for r in test_failures])
        self.state.d["blocking"] = all_blocking
        self.state.save()
        findings = {"round": rnd, "blocking": all_blocking,
                    "minor": [{"source": "reviewer", "summary": f.get("summary", ""), "evidence": f.get("evidence", "")}
                              for f in minor]}
        return clean, tpassed, flags, findings

    def gb(self, method, path, body=None):
        return http(method, f"{GROWTHBOOK_API}{path}", os.environ["GROWTHBOOK_ADMIN_PAT"], body)

    def release(self, flags, head):
        project = self.gb("GET", "/projects?limit=100")[1]["projects"][0]["id"]
        released, kept = [], []
        for slug in flags:
            if not SLUG_RE.fullmatch(slug):
                raise NeedsHuman("other", f"flag slug {slug!r} is not a valid slug; nothing released")
        for slug in flags:
            key = f"{self.app}.feature.{slug}"
            if self.gb("GET", f"/features/{key}")[0] == 200:
                kept.append(key)  # never re-enable or alter an existing flag
                continue
            status, r = self.gb("POST", "/features", {
                "id": key, "owner": "ai-factory", "valueType": "boolean", "defaultValue": "true", "project": project,
                "environments": {"production": {"enabled": True, "rules": []}}})
            if status != 200:
                raise RuntimeError(f"creating flag {key} failed: HTTP {status} {r}")
            released.append(key)
        body = (f"**Released** by Build Run [{self.run_id}]({self.run_url}) for commit `{head}`.\n\n"
                f"Enabled for everyone: {', '.join(f'`{k}`' for k in released) or 'none'}.\n"
                + (f"Left untouched (already existed): {', '.join(f'`{k}`' for k in kept)}.\n" if kept else "")
                + "\nRoll back by turning the flag off in GrowthBook.")
        self.gh(["api", f"repos/{self.app_repo}/commits/{head}/comments", "-f", f"body={body}"])
        self.state.d["release"] = {"released": released, "kept": kept}
        self.state.stage("Release", "-", "-", 0, f"{len(released)} flag(s) released")

    # --- the run

    def run(self):
        try:
            self.setup()
            base = self.state.d["base_sha"]
            findings_path = self.work / "findings-0.json"
            findings_path.write_text(json.dumps({"blocking": [], "minor": []}))
            task = self.task
            head = self.coder("1", task, str(findings_path))
            for rnd in range(1, self.lim["review_rounds"] + 1):
                head = self.pipeline(head)
                self.state.d["head_sha"] = head
                clean, tpassed, flags, findings = self.review_and_test(base, head, rnd)
                if release_gate(True, True, tpassed, clean, head, self.head()):
                    self.check_limits()
                    if flags:
                        self.release(flags, head)
                        self.state.d.update(outcome="released", message=f"Released {len(flags)} flag(s).")
                    else:
                        self.state.d.update(outcome="nothing_to_release", message="Clean, but the coder added no new flags.")
                    return
                if rnd == self.lim["review_rounds"]:
                    raise NeedsHuman("round_limit", f"{self.lim['review_rounds']} review rounds used without a clean pass")
                findings_path = self.work / f"findings-{rnd}.json"
                findings_path.write_text(json.dumps(findings, indent=2))
                summary = "\n".join(f"- [{b['source']}] {b['summary']}" for b in findings["blocking"]) or "- (none; minor findings only)"
                head = self.coder(str(rnd + 1), f"Round {rnd + 1} fix list. Resolve every blocking item:\n{summary}", str(findings_path))
        except BudgetExhausted as e:
            self.state.d.update(outcome="budget_exhausted", message=str(e))
        except NeedsHuman as e:
            self.state.d.update(outcome={"time_limit": "time_limit", "round_limit": "round_limit"}.get(e.kind, "needs_human"),
                                message=str(e))
        except Exception as e:  # noqa: BLE001 - any crash must still reach finalize
            traceback.print_exc()
            self.state.d.update(outcome="crash", message=f"{type(e).__name__}: {e}")
        finally:
            self.state.save()
        return


# --- finalize -------------------------------------------------------------------

OUTCOME_TITLES = {
    "budget_exhausted": "Build Run: budget exhausted",
    "round_limit": "Build Run: needs human (review round limit reached)",
    "time_limit": "Build Run: needs human (time limit reached)",
    "needs_human": "Build Run: needs human",
    "crash": "Build Run: crash",
    "running": "Build Run: crash (it ended without finishing)",
}


def render_summary(d):
    icon = {"released": ":white_check_mark:", "nothing_to_release": ":white_check_mark:"}.get(d["outcome"], ":x:")
    lines = [f"## Build Run Summary: {d['app']}", "",
             f"**Status**: {icon} `{d['outcome']}`  ", f"**Message**: {d['message'] or '-'}  ",
             f"**Cost**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f} cap  ",
             f"**Review passes**: {d['review_passes']}  ", f"**Final commit**: `{d['head_sha'] or '-'}`  ",
             f"**App**: https://{d['app']}.fly.dev  ", f"**Fly log viewer**: https://fly.io/apps/{d['app']}/monitoring", "",
             "| Stage | Agent | Round | Cost | Calls | Peak context | Tokens in (cached) | Tokens out | Condenser calls | Verdict |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    goal = d.get("context_goal_tokens", 100000)
    peaks = []
    for s in d["stages"]:
        u = s.get("usage")
        if u:
            peaks.append((u["peak_context"], f"{s['agent']} {s['round']}"))
            peak = f"{u['peak_context']:,}" + (" :warning:" if u["peak_context"] > goal else "")
            cols = [str(u["calls"]), peak, f"{u['prompt_tokens']:,} ({u['cache_read_tokens']:,})",
                    f"{u['completion_tokens']:,}", str(u["condenser_calls"])]
        else:
            cols = ["-"] * 5
        lines.append(f"| {s['stage']} | {s['agent']} | {s['round']} | ${s['cost_usd']:.4f} | {' | '.join(cols)} | {s['verdict']} |")
    if peaks:
        top, who = max(peaks)
        verdict = "over the goal" if top > goal else "under the goal"
        lines += ["", f"**Peak context this run**: {top:,} tokens ({who}), {verdict} of {goal:,}. "
                  "A peak is the largest prompt in a single LLM call, i.e. how big one Agent's context got."]
    rel = d.get("release")
    lines += ["", "**Release**: " + (f"released {', '.join(rel['released']) or 'nothing new'}" if rel else "not released")]
    if d["blocking"] and d["outcome"] not in ("released", "nothing_to_release"):
        lines += ["", "**Open blocking findings at the end**:"] + [f"- [{b['source']}] {b['summary']}" for b in d["blocking"]]
    return "\n".join(lines) + "\n"


def finalize():
    work = Path(os.environ["BUILD_RUN_DIR"])
    app = os.environ["APP_NAME"]
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '0')}"
    d = load_json(work / "state.json")
    if d is None:
        d = {"app": app, "issue_number": os.environ["ISSUE_NUMBER"], "run_url": run_url, "outcome": "crash",
             "message": "no state file was written; the Build Run failed before its first stage", "cap_usd": 0,
             "spent_usd": 0.0, "head_sha": None, "review_passes": 0, "stages": [], "release": None, "blocking": [],
             "commits": [], "base_sha": None}
    elif d["outcome"] == "running":
        d["message"] = d["message"] or "the Build Run process ended without recording an outcome (cancelled or killed)"
    d["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = render_summary(d)
    (work / "artifacts").mkdir(parents=True, exist_ok=True)
    (work / "artifacts" / "build-run-report.json").write_text(json.dumps(d, indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a") as f:
        f.write(summary)
    ok = d["outcome"] in ("released", "nothing_to_release")
    pat, ftoken = os.environ["FACTORY_PAT"], os.environ["FACTORY_GH_TOKEN"]
    if not ok:
        body = f"{d['message']}\n\n**Build Run**: {run_url}\n**Spent**: ${d['spent_usd']:.4f} of ${d['cap_usd'] or 0:.2f}\n\n" + summary
        (work / "issue-body.md").write_text(body)
        sh(["gh", "issue", "create", "--repo", f"{owner}/{app}", "--title", OUTCOME_TITLES.get(d["outcome"], "Build Run: crash"),
            "--body-file", str(work / "issue-body.md")], env={**os.environ, "GH_TOKEN": pat}, check=False)
    sh(["gh", "issue", "comment", d["issue_number"], "--repo", os.environ["GITHUB_REPOSITORY"], "--body",
        f"**Build Run {'finished' if ok else 'stopped'}: `{d['outcome']}`.** {d['message']} ([run]({run_url}))"],
       env={**os.environ, "GH_TOKEN": ftoken}, check=False)
    return 0 if ok else 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        BuildRun().run()
        return 0
    if cmd == "finalize":
        return finalize()
    print("usage: build_run.py run|finalize", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
