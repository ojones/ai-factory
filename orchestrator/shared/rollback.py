import json
import os
import time

from shared import http_client
from shared.shell import sh


def rollback_decision(d, enabled=True):
    outcome, commits = d.get("outcome"), d.get("commits") or []
    if outcome != "regression":
        return False, "only a regression rolls the deploy back; every other ending is fixed forward"
    if not enabled:
        return False, "rolling back regressions is switched off"
    if not commits:
        return False, "the run pushed nothing, so nothing new is deployed"
    if not d.get("base_sha"):
        return False, "there is no earlier deployed version to return to"
    return True, ""


ROLLBACK_WORKFLOW = "rollback-fly.yml"


def run_ids(app_repo, env):
    out = sh(["gh", "run", "list", "--repo", app_repo, "--workflow", ROLLBACK_WORKFLOW, "--limit", "10", "--json", "databaseId,status,conclusion"],
             env=env, check=False).stdout
    try:
        return {r["databaseId"]: r for r in json.loads(out or "[]")}
    except (ValueError, KeyError, TypeError):
        return {}


def rollback_deploy(d, app, app_repo, pat, minutes):
    base = d["base_sha"]
    env = {**os.environ, "GH_TOKEN": pat}
    try:
        before = set(run_ids(app_repo, env))
        started = sh(["gh", "workflow", "run", ROLLBACK_WORKFLOW, "--repo", app_repo, "-f", f"sha={base}"], env=env, check=False)
        if started.returncode != 0:
            return {"status": "failed", "restored": base, "reason": f"could not start {ROLLBACK_WORKFLOW} in {app_repo} (an app built before it "
                    f"existed gets it from template sync): {(started.stderr or started.stdout or '').strip()[:200]}"}
        return wait_for_rollback(app, app_repo, env, before, base, minutes)
    except Exception as e:  # noqa: BLE001 - reported, never raised: finalize must still write its Report
        return {"status": "failed", "restored": base, "reason": f"{type(e).__name__}: {str(e)[:300]}"}


def wait_for_rollback(app, app_repo, env, before, base, minutes):
    end = time.time() + minutes * 60
    while time.time() < end:
        time.sleep(10)
        done = [r for i, r in run_ids(app_repo, env).items() if i not in before and r.get("status") == "completed"]
        if done:
            return rollback_result(app, base, all(r.get("conclusion") == "success" for r in done))
    return {"status": "failed", "restored": base, "deploy": "timeout", "reason": f"the rollback did not finish within {minutes:g} minutes"}


def rollback_result(app, base, succeeded):
    if not succeeded:
        return {"status": "failed", "restored": base, "deploy": "deploy_failed", "reason": "the rollback workflow failed"}
    if healthy(app):
        return {"status": "rolled_back", "restored": base, "deploy": "healthy"}
    return {"status": "failed", "restored": base, "deploy": "unhealthy", "reason": "the rollback deployed but /api/health did not answer 200"}


def healthy(app):
    for _ in range(12):
        status, _ = http_client.request("GET", f"https://{app}.fly.dev/api/health", timeout=20)
        if status == 200:
            return True
        time.sleep(5)
    return False


def rollback_failed_run(d, pat, lim):
    go, why = rollback_decision(d, bool(lim.get("rollback_regressions", True)))
    if not go:
        d["rollback"] = {"status": "skipped", "reason": why}
        return
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    d["rollback"] = rollback_deploy(d, d["app"], f"{owner}/{d['app']}", pat, float(lim.get("rollback_timeout_minutes", 15)))
