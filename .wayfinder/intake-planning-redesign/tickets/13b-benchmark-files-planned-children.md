---
title: Benchmark files planned children
type: task
status: resolved
assignee: ojones
blocked_by: [13-planning-process.md]
---

## Question

Make the model benchmark run again now that a Build Run refuses a child that was not planned (ticket 12, ticket 13). `monitoring/benchmark.py` files an `update-app-intake` issue with the `benchmark` label and dispatches `build-run.yml` on it directly; that issue has no `factory-plan` marker and no parent, so the run stops "not planned yet", and `plan.yml` skips the `benchmark` label on purpose so production planning does not spend on it. Decide and build how a pass measures the whole run again: the planner of the candidate branch should plan each task (a pass measures planner plus Build Run, as a real request does), so the benchmark files the Intake, waits for its children, and dispatches or waits for the Build Run of the child, and scores the ending as before (the oracle, cost, rounds). Update `docs/benchmark-protocol.md`, `agents/benchmark/bench-app-spec.md` and the cost estimate (the planner adds about $0.04 to $0.10 a task).

## Added context

Found while closing ticket 13. Options to weigh: (a) dispatch `plan.yml` from the candidate branch with the Intake number (it needs a `workflow_dispatch` trigger and the same inputs), then dispatch `build-run.yml` for each child in order; (b) file the child tickets by hand from a fixed plan per task (cheaper and repeatable, but then the planner is not measured, so a planner model swap would need its own pass). The task suite has a refusal task (payments) and an ambiguous-spec task; both end at planning now (`refused`, `needs_human`), so their expected outcomes in `agents/benchmark/suite.json` move from the Build Run to the planning ending. Not blocking the live proof of the Update flow, but ticket 17 must not claim a model swap is measured until this lands.

## Resolution

Built, option (a): a pass measures planner plus Build Run as a real request does. Not run live (a pass costs about $0.80 to $3.70); `benchmark.py plan` is the dry run.

- `plan.yml` gained a `workflow_dispatch` trigger (input `issue_number`) and its job runs for a dispatch whatever the labels; the benchmark dispatches it from the candidate branch, so the planner measured is the branch's. Children inherit the Intake's `benchmark` label (`planning/file_children.INHERITED`), and `update-app-intake.yml` skips a `benchmark` child, so the production workflows never start it with the production models; `close_child`'s start label on the next child is then harmless.
- `monitoring/benchmark.py`: per task it resets the bench app, files the Update App Intake (`benchmark` label), dispatches `plan.yml`, reads the children from the sub-issues and blockers API (`child_order`), dispatches `build-run.yml` for each in order and stops at the first that does not release, then `merge_reports` adds up cost (the planner's from the spend ledger by run id), rounds and time. A task that ends at planning (`planned` is not an ending; `refused`, `needs_human`, `awaiting_secret`) is scored on that ending (`planning_report`). `dispatch_and_wait` now takes the first run newer than the one seen before the dispatch (`newest_run_after`), where it used to take the newest one listed, which could be a stale run.
- The suite: the two refusal tasks keep `refused` (now the planning ending; `refuse-secret` costs nothing because the secret scan precedes the planner); `ambiguous-spec` still expects `released` (the request pre-resolves its ambiguity, so a blocking question would be a planner failure); named-flag wording is gone from the requests (flags are `issue-<n>`, new per child by construction); `retire-named-flag` takes `{seed_flag}`, recorded by `freeze --seed-flag issue-<n>` and checked by `validate_suite` once frozen. The bench app `factory-bench` now exists (ticket 17's live proof) but must be re-seeded and frozen per `bench-app-spec.md` before a pass.
- Docs: `docs/benchmark-protocol.md` (the flow, the cost table, what it does not cover), `agents/benchmark/bench-app-spec.md`, the estimate (`estimate()`). Unit tests cover every pure part (planning ending, child order, ledger cost, planning report scoring, merged reports, the dispatch race, seed flag, label inheritance, the workflow triggers); the runner's GitHub calls are, like before, untested until a pass is run.
- Do not claim a model swap is measured until a baseline pass has been taken on the new flow.
