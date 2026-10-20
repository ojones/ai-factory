---
title: Benchmark files planned children
type: task
status: open
assignee:
blocked_by: [13-planning-process.md]
---

## Question

Make the model benchmark run again now that a Build Run refuses a child that was not planned (ticket 12, ticket 13). `monitoring/benchmark.py` files an `update-app-intake` issue with the `benchmark` label and dispatches `build-run.yml` on it directly; that issue has no `factory-plan` marker and no parent, so the run stops "not planned yet", and `plan.yml` skips the `benchmark` label on purpose so production planning does not spend on it. Decide and build how a pass measures the whole run again: the planner of the candidate branch should plan each task (a pass measures planner plus Build Run, as a real request does), so the benchmark files the Intake, waits for its children, and dispatches or waits for the Build Run of the child, and scores the ending as before (the oracle, cost, rounds). Update `docs/benchmark-protocol.md`, `agents/benchmark/bench-app-spec.md` and the cost estimate (the planner adds about $0.04 to $0.10 a task).

## Added context

Found while closing ticket 13. Options to weigh: (a) dispatch `plan.yml` from the candidate branch with the Intake number (it needs a `workflow_dispatch` trigger and the same inputs), then dispatch `build-run.yml` for each child in order; (b) file the child tickets by hand from a fixed plan per task (cheaper and repeatable, but then the planner is not measured, so a planner model swap would need its own pass). The task suite has a refusal task (payments) and an ambiguous-spec task; both end at planning now (`refused`, `needs_human`), so their expected outcomes in `agents/benchmark/suite.json` move from the Build Run to the planning ending. Not blocking the live proof of the Update flow, but ticket 17 must not claim a model swap is measured until this lands.
