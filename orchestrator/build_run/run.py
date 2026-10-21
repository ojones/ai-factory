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
from try_fix import fix_note

from build_run import endings, gate_release, review_code, track_progress, verify_deployed_app
from build_run.agent_calls import AgentCalls
from build_run.gate_release import ReleaseStep
from build_run.prepare_run import PrepareRun
from build_run.review_code import ReviewCode
from build_run.ship_code import ShipCode
from build_run.track_progress import TrackProgress
from build_run.verify_deployed_app import VerifyDeployedApp
from build_run.write_code import WriteCode


def reviewer_view(f):
    return review_code.finding_view("reviewer", f.get("summary", ""), f.get("evidence", ""), f)


def tester_view(r):
    return review_code.finding_view("tester", f"{r.get('flag')}: {r.get('check')}", r.get("evidence", ""), r)


class BuildRun(PrepareRun, AgentCalls, WriteCode, ReviewCode, ShipCode, VerifyDeployedApp, ReleaseStep, TrackProgress):
    # Sequencing only: `run` calls each step in order. Each step's code is in the mixin named above (one file each), over this object's state.
    retiring = ()  # the flags this run retires in passing (set in setup)
    fix_for = None  # the failed child this child fixes (its marker's `fix_for`), set in setup
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
        self.build_kind = "update"  # every Build Run is a planned child of an existing app; staging is not a Build Run
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
            self.drive()
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

    def drive(self):
        self.setup()
        base = self.state.d["base_sha"]
        self.failed_tests = 0
        head = self.first_coder_round()
        for rnd in range(1, self.lim["review_rounds"] + 1):
            released, head = self.play_round(base, head, rnd)
            if released:
                return

    def first_coder_round(self):
        findings_path = self.work / "findings-0.json"
        findings_path.write_text(json.dumps({"blocking": [], "minor": []}))
        return self.coder("1", self.prepare_task(), str(findings_path))

    def prepare_task(self):
        self.name_the_flag()
        task = self.task + retirement_selection.retirement_block(self.retiring)
        self.spec = self.spec_with_notes()
        self.note_retiring()
        self.stage_secret_wiring()
        return task

    def spec_with_notes(self):
        spec = (getattr(self, "spec", None) or self.task) + retirement_selection.retirement_note(self.retiring)
        return spec + fix_note.fix_note(self.fix_for) if self.fix_for else spec

    def note_retiring(self):
        if self.retiring:
            log("retiring in passing: " + ", ".join(self.retiring))
            self.state.d["retiring"] = list(self.retiring)

    def play_round(self, base, head, rnd):
        clean, blocking, minor, flags, head = self.review_and_deploy(base, head, rnd)
        tpassed, test_failures = self.test_until_decided(base, head, rnd, flags) if clean else (False, [])
        findings, findings_path = self.write_findings(rnd, head, blocking, minor, test_failures)
        if gate_release.release_gate(True, True, tpassed, clean, head, self.head()):
            self.release_clean_run(base, head, flags)
            return True, head
        self.stop_when_exhausted(rnd, test_failures)
        return False, self.coder_fix_round(rnd, findings, findings_path)

    # The reviewer sees the commit before it is pushed, so code it blocks never reaches `main`; only reviewed code is pushed,
    # and it deploys dark behind its flag until the tester has passed it.
    def review_and_deploy(self, base, head, rnd):
        while True:
            clean, blocking, minor = self.review_before_push(base, head, rnd)
            flags = self.run_flags(base, head)
            deployed, head = self.push_through_pipeline(head) if clean else (True, head)
            if deployed:
                return clean, blocking, minor, flags, head

    def push_through_pipeline(self, head):
        self.push(head)
        try:
            deployed = self.pipeline(head)
        except endings.PipelineFix as fix:
            return False, fix.head
        self.state.d["head_sha"] = deployed
        return True, deployed

    def test_until_decided(self, base, head, rnd, flags):
        retests = int(self.lim.get("test_retries", 1))
        while True:
            tpassed, test_failures, impact = self.test_deployed(base, head, rnd, flags)
            self.stop_on_regression(impact, test_failures)
            self.stop_when_live_and_failing(tpassed, test_failures, head, flags)
            if tpassed or verify_deployed_app.failed_checks(test_failures):
                return tpassed, test_failures
            retests = self.retest_or_stop(retests, test_failures)

    def stop_on_regression(self, impact, test_failures):
        if impact == "regression":
            broken = [r for r in test_failures if isinstance(r, dict) and r.get("scope") == "existing"]
            self.state.d["blocking"] = [tester_view(r) for r in broken]
            raise endings.Regression("the tester found behaviour that was live before this change no longer working: "
                                     + "; ".join(f"{r.get('check')}" for r in broken[:3]))

    def stop_when_live_and_failing(self, tpassed, test_failures, head, flags):
        failed = verify_deployed_app.failed_checks(test_failures)
        ungated = self.ungated_flags(head, flags) if failed and not tpassed else []
        if ungated:
            # The change is live with no gate (nothing reads its flag), so a failure is a failure in production: roll back.
            named = self.state.d.get("named_flag")
            self.state.d["flag_notes"] = [missing_flag.note(s, "live_and_failing", named) for s in ungated]
            self.state.d["blocking"] = [tester_view(r) for r in failed]
            raise endings.Regression(missing_flag.live_message(ungated, named, True))

    # Nothing failed, but checks were blocked or not run. The coder cannot fix that, so it gets no round for it: the
    # tester looks again at the same deployed commit, and a run that still cannot verify it stops for a person.
    def retest_or_stop(self, retests, test_failures):
        if retests <= 0:
            self.state.d["unverified"] = verify_deployed_app.unverified_checks(test_failures)
            raise run_stops.NeedsHuman("other", verify_deployed_app.unverified_message(test_failures))
        log(f"{len(test_failures)} check(s) could not be verified; testing the same deployed commit again")
        return retests - 1

    def write_findings(self, rnd, head, blocking, minor, test_failures):
        all_blocking = [reviewer_view(f) for f in blocking] + [tester_view(r) for r in verify_deployed_app.failed_checks(test_failures)]
        self.state.d["blocking"] = all_blocking
        self.state.save()
        # Kept on a clean pass too: the minor findings of a run that ships are what the retrospective learns from.
        findings = {"round": rnd, "blocking": all_blocking, "minor": [reviewer_view(f) for f in minor]}
        findings_path = self.work / f"findings-{rnd}.json"
        findings_path.write_text(json.dumps(findings, indent=2))
        self.record_round(rnd, head, all_blocking)
        return findings, findings_path

    def release_clean_run(self, base, head, flags):
        self.check_limits()
        if flags:
            self.release_and_record(flags, head)
        else:
            self.state.d.update(outcome="nothing_to_release", message="Clean, but the change added no flag, so there was nothing to release.")
        self.archive_retired_flags(base, head)

    def release_and_record(self, flags, head):
        self.release(flags, head)
        released = (self.state.d.get("release") or {}).get("released")
        if not released and self.state.d.get("flag_message"):
            self.state.d.update(outcome="nothing_to_release", message=self.state.d["flag_message"])
            return
        self.link_flags_to_issue(flags)
        self.state.d.update(outcome="released", message=f"Released {len(flags)} flag(s).")
        self.watch_release()

    def stop_when_exhausted(self, rnd, test_failures):
        if verify_deployed_app.failed_checks(test_failures):
            self.failed_tests += 1
            self.stop_when_tests_keep_failing()
        self.stop_when_rounds_are_spent(rnd)

    def coder_fix_round(self, rnd, findings, findings_path):
        summary = "\n".join(review_code.describe_finding(b) for b in findings["blocking"]) or "- (none; minor findings only)"
        return self.coder(str(rnd + 1), f"Round {rnd + 1} fix list. Resolve every blocking item:\n{summary}", str(findings_path))

    def stop_when_tests_keep_failing(self):
        failed_tests = self.failed_tests
        if failed_tests >= int(self.lim.get("test_rounds", 0) or 10**6):
            raise run_stops.NeedsHuman("round_limit", f"{failed_tests} deployed tests failed; each costs a push, a deploy and a tester pass, "
                                            "so the run stops for a person instead of trying again")

    def stop_when_rounds_are_spent(self, rnd):
        if rnd == self.lim["review_rounds"]:
            raise run_stops.NeedsHuman("round_limit", f"{self.lim['review_rounds']} review rounds used without a clean pass")
        if track_progress.stalled(self.state.d["scoreboard"], int(self.lim.get("stuck_rounds", 0))):
            raise run_stops.NeedsHuman("stuck", f"the last {self.lim['stuck_rounds']} rounds left the same checks failing and the "
                                      "same findings open; more fix rounds are not changing anything")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        BuildRun().run()
        return 0
    print("usage: python -m build_run.run run", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
