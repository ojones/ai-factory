---
title: Prove the reworked pipeline with one ordinary run, and the retrospective isolation
type: task
status: resolved
assignee: ojones
blocked_by: []
---

## Question

The review-before-push order, the tester's `new` and `existing` tags and impact, the retrospective on every run (summary on the story, improvements, bugs), the duplicate matching, template sync running only at night, and the isolated retrospective Agent have only been unit-tested. Run one small flagged Update Intake on `ojones-todo` (typically about $0.30, up to about $1; see ticket 29) and check each of those against what the docs say; then add `ready-for-factory-run` to a `factory-learning` issue to run the isolated retrospective Agent and its isolated unit tests on a real runner (about $0.50). What does a pass look like for each, and what do you fix if one does not hold?

## Added context

- What to check, in order: the reviewer reads the local commit before anything is pushed and a blocked review pushes nothing; the push deploys dark and the tester runs after it; the reviewer and tester documents have `category`, `evidence_kind`, `scope` and `improvements` in the right shape (the likeliest thing to need a tweak); mechanical flag findings come from the Orchestrator; the retrospective comments a summary on the story once and files improvements without duplicates; and for isolation, that the ACL sharing between the `runner` and `agent` accounts works for the copies it makes and the unit tests pass when run as the Agent user.
- The nightly template sync will start a real Build Run on `ojones-todo` on its own after the changes reach `main` (it needs `rollback-fly.yml`, and the lint config once ticket 15's work is merged); that run is a free exercise of the lint-config staging and the new order, so look at it before filing a separate Intake.
- The owner has deferred live runs; do this when one is wanted.

## Live results (2026-10-15)

Three Build Runs on `ojones-todo` (template sync #108 twice, keyed Intake #111) proved, in the real pipeline: the reviewer reading the local commit before any push; the push deploying dark and the tester running after it; `new`/`existing` check tags, `dark_only` impact and the `bug` label with the bugs noted on the story (not a new issue); `dark-broken` and `flag:<slug>` labels; the retrospective commenting once per run, filing improvements and lessons (#109, #115, #119) with the hidden `seen` marker; the lint-config and workflow files applied by the Orchestrator before the planner; `test_rounds` stopping at two failed deployed tests; categories recorded on the scoreboard; the pre-review check and `check_problem` staying quiet. Costs: $0.24 (blocked deploy), $0.12 (blocked deploy, stopped at once), $0.48 (sync retry, 3 passes), $0.89 (keyed Intake, 2 deployed tests failed). Not yet seen: a release, the watchdog, the isolated retrospective Agent's PR path, a regression rollback.

Found and fixed: the deploy workflow's `toJSON(secrets)` made GitHub block every Deploy run; a run GitHub never starts now stops at once with no Pipeline Agent call; the tester wrote checks that needed a different server environment than the deployed one and failed them (prompt fixed).

## Live results (2026-10-18): isolated retrospective Agent

Added `ready-for-factory-run` to the `audit_violation` lesson (Factory Run 39087071339, $0.10, 2 minutes). Held: the Agent ran as the `agent` account in `/srv/agent/run` (`AGENT_USER` and `BUILD_RUN_DIR` set), its changes were carried back through the ACLs ("changed 43 file(s); 43 in allowed paths carried over"), and the run finished green. Also, the `ready-for-factory-run` label did not exist in the repo; it was created.

Did not hold, or not seen: the proposal was rejected by validation ("agents/smoke/fixtures/audit_violation_a01.diff is not a diff of Managed App code"), so the learning-PR path was not exercised; the lesson comment says only "No change was proposed, it did not pass validation, or too many learning PRs are open" and shows the Agent's prose proposal, which names a different file (orchestrator/build_run.py). That the Agent "changed 43 files" for a one-file fix looks like the copy-in tree being counted, and is worth a look. The isolated unit tests as the Agent user were not visible in the log. Still unseen overall: a release, the watchdog, a regression rollback, a merged learning PR. Ticket 22 covers the rollback and failure path.

## Outcome

Isolation and the ACL carry-over are proven live. Remaining gaps are carried to ticket 22 (release, watchdog, rollback) and noted here: (a) why a lesson about orchestrator code produced a fixture-only change that validation rejected, (b) the 43-file count, (c) whether the unit tests run as the Agent user.
