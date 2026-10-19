---
title: Build Run domain: split build_run.py by responsibility
type: task
status: open
assignee:
blocked_by: [08c-dark-mode-is-unit-tested-and-retirement-removes-tests.md]
---

## Question

Behaviour-preserving: break `build_run.py` (2617 lines) into the `build_run/` domain folder, one file per responsibility along STEP 4.1 to 4.14 (for example prepare, coder loop, precheck, review, push, ci and deploy, pipeline diagnosis, tester, retest, rollback, release gate, outcome and report), each with its own focused tests moved out of the 1359-line `build_run_test.py`. The `BuildRun` orchestration keeps only sequencing. Planning (`plan_change`) stays in place until the planning-process ticket moves it out. Existing tests must pass unchanged in meaning before and after.

## Added context

Pure refactor, its own commits, no new behaviour; if a test of a seam is missing, add it before moving the code under it (characterize first). The domain's public interface (run a child) and its inputs (the child body and marker) are written into `docs/orchestrator-map.md`. Largest mechanical change; split across more than one session if needed, in small green commits.

**Target files in `build_run/`** (decided in ticket 04; this ticket owns the exact function-by-function mapping, tests first where a seam has none): `start_build.py` (the gate that starts a run for a child, from `update_intake.start`), `read_child.py` (the child's body and marker), `prepare_run.py` (setup, template files, secret wiring, daily cap, capacity wait, model check), `run.py` (sequencing only), `write_code.py` (coder round, protected-file check, precheck), `review_code.py` (review context, banded findings, verdict, flag and suppression findings), `ship_code.py` (push, CI and deploy wait, pipeline diagnosis), `test_deployed_app.py` (tester round, helper reconcile, `test_impact`, retest), `track_progress.py` (scoreboard, stuck detection, round records), `gate_release.py` (the release gate and Preview Token), `rollback_deploy.py` (regression decision and the CI rollback). The Agent runtime is already in `shared/agent_runner`; the run summary and finalize go to `retrospective/`; the watchdog and `release` go to `flag_lifecycle/`. Move each file's tests out of the 1,359-line `build_run_test.py`.
