---
title: Queued runs silently dropped by concurrency groups
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

With `cancel-in-progress: false`, GitHub keeps one running and at most one pending run per concurrency group, and cancels an older pending run when a newer one arrives. The per-app group `build-run-${{ inputs.app_name }}` in `.github/workflows/build-run.yml` (and the shared `app-staging` group in `app-staging.yml` and `teardown.yml`) therefore loses the middle run when three are queued, which breaks "one Build Run per change set". Make queued runs reliable: add `queue: max` (GitHub changelog, 2026-05-07, up to 100 queued) or choose another mechanism, then make a lost Intake detectable (an `intake` issue labelled ready that never produced a run is flagged).

## Added context

- Verify `queue: max` behaves as documented on a real run with two quickly queued dispatches before relying on it. That check is the part not yet done.
- Check the other concurrency uses and the wait loop in `orchestrator/build_run.py` (~L511, `max_simultaneous_build_runs`) for the same assumption.
- Source: https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues
- Test bed: `ojones-todo` (see the plan in the conversation of 2026-10-12): first prove the behaviour with two throwaway probe workflows (current semantics vs `queue: max`), three dispatches each, so nothing real is risked; only then add `queue: max` to `build-run.yml` and confirm on the real workflow by dispatching three Build Runs at `ojones-todo` with a nonexistent issue number (they fail in setup within minutes, costing no model spend).
- Result (2026-10-12): two probe workflows, three dispatches each. Without `queue: max`: run 1 ran, run 2 was cancelled 4 s after creation, run 3 ran. With `queue: max`: all three ran in order. `queue: max` is now set in `build-run.yml` (commit after b42f8eb) and checked by INV-18. Not done: `app-staging.yml` and `teardown.yml` share a group (`app-staging`) with the same weakness (the first is a job-level concurrency block, whose syntax for `queue` was not probed); and a labelled Intake that never produced a run is still not detected.

## Resolution

Resolved: `queue: max` is on the per-app Build Run group (verified with a probe 2026-10-12; INV-18), and Update Intake starts one change set at a time so an app never has two pending runs (INV-23). The shared `app-staging` group is not changed; staging is per new app and rare.
