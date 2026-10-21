import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from shared import child_tickets, github, preview_token
from try_fix import event

CHECKS = ("ci_green", "deploy_healthy", "flag_service", "preview_token", "secrets_present", "smoke")
PIPELINE = ("Test Gate", "Build", "Deploy to Fly")
STAGING_SECRETS = ("FLY_API_TOKEN", "GROWTHBOOK_CLIENT_KEY", "PREVIEW_TOKEN")


class Deps:
    def __init__(self, http, runs, secret_names, flag_connection, sleep=time.sleep, now=time.time):
        self.http, self.runs, self.secret_names, self.flag_connection, self.sleep, self.now = http, runs, secret_names, flag_connection, sleep, now


def result(check, ok, detail):
    return {"check": check, "ok": bool(ok), "detail": detail}


def wait_until(deps, condition, timeout, every):
    end = deps.now() + timeout
    while True:
        got = condition()
        if got:
            return got
        if deps.now() >= end:
            return None
        deps.sleep(every)


def ci_green(deps, sha, timeout=900):
    def settled():
        runs = {r["name"]: r for r in deps.runs(sha)}
        if all(runs.get(n, {}).get("status") == "completed" for n in PIPELINE):
            return runs
        failed = [n for n in PIPELINE if runs.get(n, {}).get("status") == "completed" and runs[n].get("conclusion") != "success"]
        return runs if failed else None

    runs = wait_until(deps, settled, timeout, 15)
    if runs is None:
        return result("ci_green", False, f"the seed commit's pipeline did not finish within {timeout // 60} minutes")
    bad = [f"{n}: {runs.get(n, {}).get('conclusion') or 'not run'}" for n in PIPELINE if runs.get(n, {}).get("conclusion") != "success"]
    return result("ci_green", not bad, "; ".join(bad) if bad else "Test Gate, Build and Deploy to Fly all succeeded")


def deploy_healthy(deps, app, timeout=120):
    def healthy():
        try:
            status, _, body = deps.http("GET", f"https://{app}.fly.dev/api/health", {})
        except OSError:
            return None
        return status == 200 and json.loads(body or "{}").get("status") == "ok" or None

    ok = wait_until(deps, healthy, timeout, 5)
    return result("deploy_healthy", ok, "/api/health answers 200 ok" if ok else f"/api/health did not answer 200 ok within {timeout} seconds")


def flag_service(deps, app):
    try:
        connected = deps.flag_connection()
    except Exception as e:  # noqa: BLE001 - a failed lookup is a failed check
        return result("flag_service", False, f"GrowthBook could not be asked about the app's SDK connection: {type(e).__name__}: {str(e)[:150]}")
    return result("flag_service", connected, "GrowthBook has the app's SDK connection" if connected else f"GrowthBook has no SDK connection named `{app}`")


def preview_token_path(deps, app, token):
    base = f"https://{app}.fly.dev/"
    try:
        _, good, _ = deps.http("GET", f"{base}?preview={token}", {})
        _, bad, _ = deps.http("GET", f"{base}?preview=not-the-token", {})
    except OSError as e:
        return result("preview_token", False, f"the app could not be reached: {type(e).__name__}")
    if "preview=" not in good.get("set-cookie", ""):
        return result("preview_token", False, "a request with the Preview Token was not given the preview cookie")
    if "preview=" in bad.get("set-cookie", ""):
        return result("preview_token", False, "a request with a wrong token was given the preview cookie")
    return result("preview_token", True, "the right token is given the preview cookie and a wrong one is not")


def secrets_present(deps, declared):
    have = deps.secret_names()
    missing = [n for n in list(STAGING_SECRETS) + list(declared) if n not in have]
    return result("secrets_present", not missing, "missing: " + ", ".join(missing) if missing else "all " + str(len(STAGING_SECRETS) + len(declared)) + " secrets are set")


def smoke(deps, app):
    try:
        status, _, _ = deps.http("GET", f"https://{app}.fly.dev/", {})
    except OSError as e:
        return result("smoke", False, f"the app could not be reached: {type(e).__name__}")
    return result("smoke", status == 200, f"the front page answered {status}")


def verify(deps, app, sha, token, declared=(), timeouts=None):
    t = timeouts or {}
    steps = [lambda: ci_green(deps, sha, t.get("ci", 900)), lambda: deploy_healthy(deps, app, t.get("health", 120)),
             lambda: flag_service(deps, app), lambda: preview_token_path(deps, app, token),
             lambda: secrets_present(deps, declared), lambda: smoke(deps, app)]
    out = []
    for check, step in zip(CHECKS, steps):
        try:
            out.append(step())
        except Exception as e:  # noqa: BLE001
            out.append(result(check, False, f"{type(e).__name__}: {str(e)[:200]}"))
    return out


def failure_events(app, number, results):
    return [event.make("staging", "failure", app, f"staging check {r['check']} failed: {r['detail']}", r["check"], story=number)
            for r in results if not r["ok"]]


def report(results):
    lines = ["**Infrastructure verified.**" if all(r["ok"] for r in results) else "**Infrastructure check failed.**", ""]
    lines += [f"- {'passed' if r['ok'] else 'FAILED'} `{r['check']}`: {r['detail']}" for r in results]
    return "\n".join(lines)


def fetch(method, url, headers):
    req = urllib.request.Request(url, method=method, headers=headers)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")


class LiveProbes:
    def __init__(self, env, app_repo, app):
        self.pat, self.admin, self.app_repo, self.app = env["FACTORY_PAT"], env["GROWTHBOOK_ADMIN_PAT"], app_repo, app
        self.api = f"{env.get('GROWTHBOOK_API_HOST', 'https://ai-factory-growthbook.fly.dev:3100')}/api/v1"

    def runs(self, commit):
        p = github.run(["run", "list", "--repo", self.app_repo, "--commit", commit, "--json", "workflowName,status,conclusion", "--limit", "30"], self.pat)
        return [{"name": r["workflowName"], "status": r["status"], "conclusion": r["conclusion"]} for r in json.loads(p.stdout or "[]")]

    def secret_names(self):
        p = github.run(["secret", "list", "--repo", self.app_repo, "--json", "name"], self.pat)
        return {x["name"] for x in json.loads(p.stdout or "[]")}

    def flag_connection(self):
        req = urllib.request.Request(f"{self.api}/sdk-connections?limit=100", headers={"Authorization": f"Bearer {self.admin}"})
        found = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return any(c.get("name") == self.app for c in found.get("connections") or [])


def declared_secret_names(repo, number, pat):
    body = json.loads(github.run(["issue", "view", number, "--repo", repo, "--json", "body"], pat).stdout)["body"]
    return [x["name"] for x in child_tickets.read_marker(body).get("secrets") or []]


def publish_report(env, repo, number, text):
    print(text)
    with open(env.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as f:
        f.write(text + "\n")
    github.run(["issue", "comment", number, "--repo", repo, "--body", text], env.get("GH_TOKEN", env["FACTORY_PAT"]))


def main():
    e = os.environ
    repo, number, app, sha = e["FACTORY_REPO"], e["ISSUE_NUMBER"], e["APP_NAME"], e["SEED_SHA"]
    probes = LiveProbes(e, f"{repo.split('/')[0]}/{app}", app)
    declared = declared_secret_names(repo, number, e["FACTORY_PAT"])
    results = verify(Deps(fetch, probes.runs, probes.secret_names, probes.flag_connection), app, sha, preview_token.for_app(e["PREVIEW_MASTER_SECRET"], app), declared)
    publish_report(e, repo, number, report(results))
    if e.get("FAILURE_EVENTS_FILE"):
        event.dump(failure_events(app, number, results), Path(e["FAILURE_EVENTS_FILE"]))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
