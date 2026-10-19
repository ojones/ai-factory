---
title: Flag Lifecycle domain
type: task
status: open
assignee:
blocked_by: [07-pilot-maintenance-and-monitoring.md]
---

## Question

Make the Flag Lifecycle domain (`flag_lifecycle/`, STEP 5.1 to 5.7) a folder whose files each do one thing (for example slug, create, release, retire, verify) and make it deterministic: slug `issue-<n>` from the story number (unique by construction); an idempotent `ensure_feature` at the start of a run (production off, `flags.json` entry written before the coder starts); `release` only switches it on; the Starter `withFlag(slug, on, fn)` helper and an `npm run check` step that fails when a slug lacks a flag-off and a flag-on test or has more than one entry point (cases in `agents/lint-fixtures/cases.json`); the retirement verifier extended to tests and `flags.json`; ride-along selection, soak and `approve-retire` kept. Unit tests for every transition in the group's state machine (STEP 5.1 to 5.7).

## Added context

Source plan: "Changes 10". Update INV-39 and add "a flag's slug is `issue-<n>` of its story". Works on today's story issues, so it can land before the planner moves. The Build Run domain calls this domain only through its small interface (ensure, release, retire); `build_run.py` is edited just enough to call it, the split is the Build ticket.
