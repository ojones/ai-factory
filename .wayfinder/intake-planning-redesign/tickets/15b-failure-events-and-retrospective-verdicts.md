---
title: Failure events and Retrospective verdicts
type: task
status: resolved
assignee: ojones
blocked_by: [15-try-fix-domain.md]
---

## Question

Build steps 6.2 and 6.7 of the new "From a failure to a fix" rule in `docs/flow-spec.md`. Add `try_fix/event.py` (the failure event: source, severity, app, story, fingerprint, summary, evidence, flag, released, a stable key) and `try_fix/collect_events.py` (events from a run's facts: outcome, tester `bugs`, `dark_broken`, final minor findings, improvements, `flag_notes`, unverified checks, watchdog, rollback; now also the warnings dropped today: dark-only failures, `blocked` and `not_run` checks). Add `retrospective/event_verdicts.py` and extend `agents/prompts/retrospective.md`: the Agent returns, per event, `{key, verdict fix|record, target managed_app|factory, cause, reason}`; code enforces that a failure is never downgraded and that a warning is fixed only with a reason, plus the bounds `fix_attempts_max` and a new `limits.fix_events_per_app_per_day`. A batch mode judges a scan's events with no Build Run (6.7): input is the event batch and the App State only, one call per scan, under `retrospective_cost_cap_usd`. `lesson_records.wants_fix_request` becomes "any event with verdict fix". Stop filing managed-app Suggestion issues (`minor_findings`, `improvement_issues`); factory-target items stay `factory-learning` records. `staging/verify_infrastructure.py` emits an event on a failed check. Add invariant NEW-A (every event gets a verdict) to `invariants_test.py` and the table. Unit tests for every item; move first, then change.

## Added context

Decisions (owner, 2026-10-19): the Retrospective alone names cause, target and verdict; events are judged in batches; warnings are fixed only on a `fix` verdict; app Suggestion issues are dropped. Flow spec: "From a failure to a fix", steps 6.2, 6.7, 3.2 edge. Boundary: `staging` may import `try_fix`; `retrospective` already may.

## Resolution

Built. Failure events and the Retrospective's verdicts exist; nothing yet files a ticket from a `fix` verdict (that is 15c and 15d).

- `try_fix/event.py`: the event (source, severity, app, story, fingerprint, summary, evidence, flag, released) with a stable key. `try_fix/collect_events.py`: a run's own ending is one `failure` (not a good ending, an answer, or `provider_blocked`); warnings are the dark/unverified tester notes of a good run, minor findings, app improvements and flag notes (capped at 8). A failed run's tester bugs stay part of its failure. Factory improvements stay `factory-learning` records. A `blocked` or `not_run` check now reaches the facts as `unverified` (`verify_deployed_app.unverified_checks`, saved before the stop).
- `retrospective/event_verdicts.py` (the rules are code): a failure is always `fix`; a warning is `fix` only if the Agent says so with a reason and the app is under `fix_events_per_app_per_day` (3, new in `agents/profiles.yml`; counted from the app's `bug` tickets filed today by `fix_budget.py`); otherwise `record`. Target and cause come from the Agent, default `managed_app`. INV-58 holds it.
- `run_retrospective.py`: facts carry `events`; the prompt asks the Agent for a per-event verdict; warnings the Agent did not judge (it did not run, or left them out) go to one batch call (`judge_events.answer`) under `retrospective_cost_cap_usd` with a scoped credential; the verdicts are saved to `artifacts/retrospective-verdicts.json`, logged and listed in the story's retrospective comment. `lesson_records.wants_fix_request` is now "the run's ending is a failure event" (the same outcomes as before), so ticket 15's filing is unchanged until 15d.
- STEP 6.7: `python -m retrospective.judge_events <events.json> <verdicts.json>` judges a batch with no Build Run in one call and falls back to the defaults if the model is unreachable. `staging/verify_infrastructure.py` writes one failure event per failed check to `FAILURE_EVENTS_FILE` when set.
- Dropped: the Suggestion issues in a Managed App's repo (`minor_findings`, `improvement_issues`); the `factory-learning` issues stay.

Not done, by design: no workflow calls `judge_events` yet (the scan sources arrive in ticket 16, and `stage.sh` does not yet pass `FAILURE_EVENTS_FILE`); the daily warning limit counts nothing until 15d files `bug` tickets; the verdict's `fix` for a warning is only logged and reported until 15c and 15d. The Agent's verdicts are unmeasured on real runs.
