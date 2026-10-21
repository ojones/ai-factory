import json
import os
import subprocess
import time

from shared import (
    agent_output,
    github,
    http_client,
    run_stops,
)
from shared.shell import sh

from build_run import endings

NOT_STARTED_CONCLUSIONS = ("action_required", "startup_failure")


PIPELINE = [("Test Gate", "test-gate.yml"), ("Build", "build.yml"), ("Deploy to Fly", "deploy-fly.yml")]


class ShipCode:
    def push(self, head):
        self.check_limits()
        sh(["git", "push", "-q", "origin", "HEAD:main"], cwd=self.app_dir, env={**os.environ, **github.git_auth_env(self.auth_header)})
        self.state.d["head_sha"] = head
        self.state.d["commits"].append(head)
        self.state.stage("Push", "-", "-", 0, f"pushed {head[:8]}")

    def wait_run(self, workflow, sha):
        give_up = time.time() + self.lim["pipeline_timeout_minutes"] * 60
        while time.time() < give_up:
            self.check_limits()
            out = self.gh(["run", "list", "--repo", self.app_repo, "--workflow", workflow, "--limit", "30",
                           "--json", "databaseId,headSha,status,conclusion,url"]).stdout
            runs = sorted((r for r in json.loads(out) if r["headSha"] == sha), key=lambda r: r["databaseId"])
            runs = [r for r in runs if not (workflow == "deploy-fly.yml" and r["status"] == "completed"
                                            and self.deploy_skipped(r["databaseId"]))]
            if runs and runs[-1]["status"] == "completed":
                return runs[-1]
            time.sleep(10)
        raise run_stops.NeedsHuman("pipeline", f"{workflow} did not finish for {sha[:8]} within {self.lim['pipeline_timeout_minutes']} minutes")

    def deploy_skipped(self, run_id):
        out = self.gh(["run", "view", str(run_id), "--repo", self.app_repo, "--json", "jobs"], check=False).stdout
        try:
            jobs = json.loads(out).get("jobs", [])
        except ValueError:
            return False
        return any(j.get("name") == "deploy" and j.get("conclusion") == "skipped" for j in jobs)

    def healthy(self):
        for _ in range(12):
            status, body = http_client.request("GET", f"https://{self.app}.fly.dev/api/health", timeout=20)
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
        retries, n = self.lim["pipeline_retries"], 0
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
                self.state.stage("CI / Build / Deploy", "-", "-", 0, f"green, deployed {sha[:8]}")
                return sha
            if failed[1] and failed[1]["conclusion"] in NOT_STARTED_CONCLUSIONS:
                raise run_stops.NeedsHuman("pipeline", f"{failed[0]} did not start: GitHub ended the run as {failed[1]['conclusion']!r} before any job ran "
                                             f"({failed[1]['url']}). Approve or fix it in the app's Actions tab, then add `proceed-with-change` again.")
            n += 1
            ctx = self.failure_context(failed, sha, n)
            url = failed[1]["url"] if failed[1] else f"https://github.com/{self.app_repo}/actions"
            diag, cost, usage = self.agent_json(
                "pipeline", f"p{n}", {"head_sha": sha, "failure_run_url": url, "context_dir": ctx,
                                      "diagnosis_path": self.work / f"diagnosis-{n}.json"},
                self.work / f"diagnosis-{n}.json", check=lambda d: d.get("category") in ("code", "workflow", "infra", "flaky"))
            diag = agent_output.load_json(self.work / f"diagnosis-{n}.json")
            self.state.stage(f"{failed[0]} failed", "pipeline", n, cost, diag["category"], usage)
            cat = diag["category"]
            if cat in ("flaky", "infra") and diag.get("retry_recommended") and retries > 0:
                retries -= 1
                if failed[1]:
                    self.gh(["run", "rerun", str(failed[1]["databaseId"]), "--repo", self.app_repo, "--failed"], check=False)
                time.sleep(20)
                continue
            if cat == "code" and diag.get("fix_request") and getattr(self, "pipeline_fixes", 0) < self.lim["pipeline_fix_attempts"]:
                self.pipeline_fixes = getattr(self, "pipeline_fixes", 0) + 1
                raise endings.PipelineFix(self.coder(f"fix{self.pipeline_fixes}", diag["fix_request"], str(self.work / "findings-none.json")))
            raise run_stops.NeedsHuman("pipeline", f"{failed[0]} failed ({cat}): {diag.get('summary', '')[:500]}")
