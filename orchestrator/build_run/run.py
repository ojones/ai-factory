# Build Run orchestrator (ARCHITECTURE.md → Agents and Build Run stages): coder → CI/deploy dark → reviewer + tester → fix loop → release.
# `run` only sequences the steps; each step's code is in the file named for it in this folder. `run/state.json` is updated after every stage, so a
# crash, breach or killed job still reports (retrospective/finalize.py).
#
# Agents are OpenHands subprocesses with a whitelisted environment. They never hold the PAT, the GrowthBook admin key, the Fly token or the
# DeepInfra parent key; the coder only commits, and this process pushes.
#
# Usage: python -m build_run.run run   (PYTHONPATH=orchestrator; run by .github/workflows/build-run.yml)
import base64
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from flag_lifecycle import (
    missing_flag,
    retirement_selection,
)
from shared import (
    config,
    outcomes,
    run_stops,
)
from shared.console import log
from shared.shell import sh
from try_fix import fix_request

from build_run import endings, gate_release, review_code, track_progress, verify_deployed_app
from build_run.agent_calls import AgentCalls
from build_run.gate_release import ReleaseStep
from build_run.plan_change import PlanChange
from build_run.prepare_run import PrepareRun
from build_run.review_code import ReviewCode
from build_run.ship_code import ShipCode
from build_run.track_progress import TrackProgress
from build_run.verify_deployed_app import VerifyDeployedApp
from build_run.write_code import WriteCode


class BuildRun(PrepareRun, AgentCalls, PlanChange, WriteCode, ReviewCode, ShipCode, VerifyDeployedApp, ReleaseStep, TrackProgress):
    # Sequencing only: `run` calls each step in order. Each step's code is in the mixin named above (one file each), over this object's state.
    retiring = ()  # the flags this run retires in passing (set in setup)
    retry_state = {}  # the story's retry state from its issue (fix_request.retry_state)
    reuse_flags = []  # the flag(s) a retried story keeps through every attempt
    story_flags = ()  # the flag this run named for the story (flag_slug.py); it is switched on at release whether or not this run created it
    flag_issues = {}  # slug -> number of the story each released flag came from (from the State issue)
    declared_secrets = ()  # the secrets recorded on the Intake, checked at the start of the run (`setup`)
    agent_user = None  # set in __init__ from AGENT_USER; a class default so a bare test instance runs Agents as the same account

    def __init__(self):
        e = os.environ
        self.app = e["APP_NAME"]
        self.issue = e["ISSUE_NUMBER"]
        if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", self.app) or len(self.app) > 30 or not self.issue.isdigit():
            raise SystemExit(f"invalid inputs: app_name={self.app!r} issue_number={self.issue!r}")
        self.factory_repo = e["GITHUB_REPOSITORY"]
        self.issue_url = f"https://github.com/{self.factory_repo}/issues/{self.issue}"
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
        self.cfg = config.load()
        self.lim = self.cfg["limits"]
        self.state = track_progress.State(self.work / "state.json", self.app, self.issue, self.run_url)
        self.start = time.time()
        self.deadline = self.start + self.lim["time_limit_minutes"] * 60
        self.cap = None
        self.meter = None
        self._usage = None
        # limits.agent_isolation: user -> the workflow created this unprivileged account and put the work directories where only it
        # and the runner can reach them; every Agent then runs as it.
        self.agent_user = e.get("AGENT_USER") or None
        self.preview = None
        self.build_kind = "first build"  # becomes "update" in setup() when the base commit has history
        self.auth_header = "Authorization: Basic " + base64.b64encode(
            f"x-access-token:{self.pat}".encode()).decode()
        print(f"::add-mask::{self.auth_header.split()[-1]}", flush=True)

    def gh(self, args, token=None, check=True):
        return sh(["gh", *args], env={**os.environ, "GH_TOKEN": token or self.pat}, check=check)

    def git(self, *args, check=True, cwd=None):
        return sh(["git", *args], cwd=cwd or self.app_dir, check=check)

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()

    def check_limits(self):
        if self.meter and self.cap is not None and self.state.d["spent_usd"] >= self.cap:
            raise run_stops.BudgetExhausted(f"${self.state.d['spent_usd']:.4f} spent against a ${self.cap:.2f} cap")
        if time.time() > self.deadline:
            raise run_stops.NeedsHuman("time_limit", f"the {self.lim['time_limit_minutes']}-minute time limit was reached")

    def record_spend(self, jwt):
        self.state.d["spent_usd"] = round(self.meter.refresh(jwt), 6)
        self.state.save()
        return self.state.d["spent_usd"]

    def run(self):
        try:
            self.setup()
            if self.update_intake and not self.plan_meta and self.lim.get("planner_enabled", True):
                if self.plan_change():
                    return
            base = self.state.d["base_sha"]
            findings_path = self.work / "findings-0.json"
            findings_path.write_text(json.dumps({"blocking": [], "minor": []}))
            self.name_the_flag()
            task = self.task + retirement_selection.retirement_block(self.retiring)
            self.spec = (getattr(self, "spec", None) or self.task) + retirement_selection.retirement_note(self.retiring)
            self.spec += fix_request.retry_note(self.reuse_flags, self.retry_state.get("attempt"))
            if self.retiring:
                log("retiring in passing: " + ", ".join(self.retiring))
                self.state.d["retiring"] = list(self.retiring)
            self.stage_secret_wiring()
            head = self.coder("1", task, str(findings_path))
            failed_tests = 0
            for rnd in range(1, self.lim["review_rounds"] + 1):
                # The reviewer sees the commit before it is pushed, so code it blocks never reaches `main`; only reviewed code is pushed,
                # and it deploys dark behind its flag until the tester has passed it.
                while True:
                    clean, blocking, minor = self.review_before_push(base, head, rnd)
                    flags = self.run_flags(base, head)
                    if not clean:
                        break
                    self.push(head)
                    try:
                        head = self.pipeline(head)
                    except endings.PipelineFix as fix:
                        head = fix.head
                        continue
                    self.state.d["head_sha"] = head
                    break
                tpassed, test_failures = False, []
                if clean:
                    retests = int(self.lim.get("test_retries", 1))
                    while True:
                        tpassed, test_failures, impact = self.test_deployed(base, head, rnd, flags)
                        if impact == "regression":
                            broken = [r for r in test_failures if isinstance(r, dict) and r.get("scope") == "existing"]
                            self.state.d["blocking"] = [review_code.finding_view("tester", f"{r.get('flag')}: {r.get('check')}", r.get("evidence", ""), r) for r in broken]
                            raise endings.Regression("the tester found behaviour that was live before this change no longer working: "
                                             + "; ".join(f"{r.get('check')}" for r in broken[:3]))
                        if not tpassed and verify_deployed_app.failed_checks(test_failures):
                            ungated = self.ungated_flags(head, flags)
                            if ungated:
                                # The change is live with no gate (nothing reads its flag), so a failure is a failure in production: roll back.
                                named = self.state.d.get("named_flag")
                                self.state.d["flag_notes"] = [missing_flag.note(s, "live_and_failing", named) for s in ungated]
                                self.state.d["blocking"] = [review_code.finding_view("tester", f"{r.get('flag')}: {r.get('check')}", r.get("evidence", ""), r)
                                                            for r in verify_deployed_app.failed_checks(test_failures)]
                                raise endings.Regression(missing_flag.live_message(ungated, named, True))
                        if tpassed or verify_deployed_app.failed_checks(test_failures):
                            break
                        # Nothing failed, but checks were blocked or not run. The coder cannot fix that, so it gets no round for it: the
                        # tester looks again at the same deployed commit, and a run that still cannot verify it stops for a person.
                        if retests <= 0:
                            raise run_stops.NeedsHuman("other", verify_deployed_app.unverified_message(test_failures))
                        retests -= 1
                        log(f"{len(test_failures)} check(s) could not be verified; testing the same deployed commit again")
                all_blocking = (
                    [review_code.finding_view("reviewer", f.get("summary", ""), f.get("evidence", ""), f) for f in blocking]
                    + [review_code.finding_view("tester", f"{r.get('flag')}: {r.get('check')}", r.get("evidence", ""), r) for r in verify_deployed_app.failed_checks(test_failures)])
                self.state.d["blocking"] = all_blocking
                self.state.save()
                # Kept on a clean pass too: the minor findings of a run that ships are what the retrospective learns from.
                findings = {"round": rnd, "blocking": all_blocking,
                            "minor": [review_code.finding_view("reviewer", f.get("summary", ""), f.get("evidence", ""), f) for f in minor]}
                findings_path = self.work / f"findings-{rnd}.json"
                findings_path.write_text(json.dumps(findings, indent=2))
                self.record_round(rnd, head, findings["blocking"])
                if gate_release.release_gate(True, True, tpassed, clean, head, self.head()):
                    self.check_limits()
                    if flags:
                        self.release(flags, head)
                        released = (self.state.d.get("release") or {}).get("released")
                        if not released and self.state.d.get("flag_message"):
                            self.state.d.update(outcome="nothing_to_release", message=self.state.d["flag_message"])
                        else:
                            self.link_flags_to_issue(flags)
                            self.state.d.update(outcome="released", message=f"Released {len(flags)} flag(s).")
                            self.watch_release()
                    else:
                        self.state.d.update(outcome="nothing_to_release", message=(
                            "First build deployed and live; it has no flags to release." if self.build_kind == "first build"
                            else "Clean, but the update added no flag, so there was nothing to release."))
                    self.archive_retired_flags(base, head)
                    return
                if verify_deployed_app.failed_checks(test_failures):
                    failed_tests += 1
                    if failed_tests >= int(self.lim.get("test_rounds", 0) or 10**6):
                        raise run_stops.NeedsHuman("round_limit", f"{failed_tests} deployed tests failed; each costs a push, a deploy and a tester pass, "
                                                        "so the run stops for a person instead of trying again")
                if rnd == self.lim["review_rounds"]:
                    raise run_stops.NeedsHuman("round_limit", f"{self.lim['review_rounds']} review rounds used without a clean pass")
                if track_progress.stalled(self.state.d["scoreboard"], int(self.lim.get("stuck_rounds", 0))):
                    raise run_stops.NeedsHuman("stuck", f"the last {self.lim['stuck_rounds']} rounds left the same checks failing and the "
                                              "same findings open; more fix rounds are not changing anything")
                summary = "\n".join(review_code.describe_finding(b) for b in findings["blocking"]) or "- (none; minor findings only)"
                head = self.coder(str(rnd + 1), f"Round {rnd + 1} fix list. Resolve every blocking item:\n{summary}", str(findings_path))
        except endings.NothingToDo as e:
            self.state.d.update(outcome="nothing_to_release", message=str(e))
        except endings.Regression as e:
            self.state.d.update(outcome="regression", message=str(e))
        except run_stops.FlagMissing as e:
            self.state.d.update(outcome=outcomes.FLAG_MISSING, message=str(e))
        except endings.Refused as e:
            self.state.d.update(outcome="refused", message=str(e))
        except endings.AwaitingSecret as e:
            self.state.d.update(outcome="awaiting_secret", message=str(e))
        except run_stops.ProviderBlocked as e:
            self.state.d.update(outcome="provider_blocked", message=str(e))
        except run_stops.BudgetExhausted as e:
            self.state.d.update(outcome="budget_exhausted", message=str(e))
        except run_stops.NeedsHuman as e:
            outcome, message = endings.ending_for(e.kind, str(e), self.state.d.get("spent_usd"), self.cap)
            self.state.d.update(outcome=outcome, message=message)
        except Exception as e:  # noqa: BLE001 - any crash must still reach finalize
            traceback.print_exc()
            self.state.d.update(outcome="crash", message=f"{type(e).__name__}: {e}")
        finally:
            self.state.save()
        return


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        BuildRun().run()
        return 0
    print("usage: python -m build_run.run run", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
