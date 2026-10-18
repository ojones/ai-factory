---
title: Production feedback loop into Intake and lessons
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

The watchdog (decided) catches regressions shortly after a release. A bug that surfaces days later reaches the Orchestrator only if the owner files it. How do runtime errors and escaped defects from deployed apps become a bug Intake or a `factory-learning` lesson without a human? Decide the signal (structured JSON logs on Fly, health checks, an `escaped-defect` label in the app repo), who collects it and how often, how to deduplicate and rate-limit it so one noisy app cannot flood the trackers, and when a signal becomes a bug Intake versus only a lesson.

## Added context

- STANDARDS-VISIBILITY.md already requires structured logs to stdout and a global uncaught-exception handler; the Build Run Summary links the Fly log viewer.
- `orchestrator/postmortem.py` already has fingerprinting, `record_issue` and `record_minors` to reuse; `MAX_MINORS` shows the flood-control pattern.
- A fix triggered this way is an update, so it follows the flag policy and gate (see the open question on unflagged fixes in the plan).
- Test bed: `ojones-todo` already has a repeatable source of production errors (the deliberately noisy `fast-heartbeat` change, whose flag the watchdog switched off; the code is still in the app, so re-enabling the flag by hand in GrowthBook produces error-level logs on demand).

## Resolution

Signal: Fly error logs (fingerprinted) plus owner-written `escaped-defect` issues. Collected every six hours (Fly's log buffer is short). One open Intake per fingerprint, one open per app, 2 new per app per day, 3 occurrences minimum. Every qualifying signal auto-starts an Update Intake with no readiness check or planner veto, flagged like any update; the 2-attempt fix-request chain is the backstop, and piled-up failures are the evidence for adding a readiness check later. Built in `orchestrator/production_feedback.py` (INV-31). Not yet run against a real app; test bed is `ojones-todo` with `fast-heartbeat` re-enabled.
