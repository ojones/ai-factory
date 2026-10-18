---
title: Run the planner fixtures' requests through the live planner
type: task
status: open
assignee:
blocked_by: []
---

## Question

`agents/planner-fixtures/cases.json` (ticket 27) proves the plan checker against plans shaped like the real mistakes, but nothing yet shows the planner stops *making* them. Add the Intake text and expected shape (number of change sets, which are `internal_only`, blocked or not) to each case, and a runner that gives the live planner each request over a small fixed app checkout (as `agents/smoke-coder` does for the coder) and scores the plan with `validate_plan` and the expected shape. Cost is a few cents per case. Run it on every planner prompt change and when the planner model is swapped; record the baseline in `docs/benchmark-protocol.md`.

## Added context

- The planner reads the repository, so the runner needs a fixed checkout; reuse the bench app from ticket 24 if it is ready.
- Related: ticket 19 (plan_gap lessons per run), ticket 23 (smoke fixtures under the new schema).
