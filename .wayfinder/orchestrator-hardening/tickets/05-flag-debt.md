---
title: Flag debt and retirement proposals
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

Every update adds a flag, and flags are retired only when the owner asks (STANDARDS-FEATURE-FLAGS.md; the advice says to remove a gate after an observation period). After many updates an app carries dozens of released flags, dead branches and more on/off combinations than any tester covers. How is flag debt kept in check while retirement stays owner-approved? Decide when a released flag becomes a retirement candidate (age, no flips, no incidents), where the proposal appears (the morning digest, the App State issue, a retirement Intake draft), whether the Orchestrator may draft the retirement change for the owner to approve, and what keeps the rollback lever for recent releases.

## Added context

- `flags.json` is the manifest; the release step never re-enables a flag, so a released flag "doubles as a rollback lever" (STANDARDS-FEATURE-FLAGS.md).
- Retirement is a normal Intake, and the Glossary defines Retire as owner-requested only.
- Tension to settle: more flags mean more states to test; fewer flags mean losing per-update rollback.
- Test bed: `ojones-todo` has real flag debt: `update-todo-store`, `patch-todo-endpoint`, `filter-todos-by-done` and `delete-todo-endpoint` are released, `heartbeat` was never released, `fast-heartbeat` was switched off by the watchdog, and PUT and PATCH duplicate each other. Retiring them through an Update Intake ('remove flag X and its code path') is the one path the Factory has never run for real.
- Result (2026-10-12), three retirement Update Intakes filed at once for `ojones-todo` (also the real-workflow check that `queue: max` keeps every queued run: all three ran in order, none cancelled). Outcomes: `filter-todos-by-done` released in one round ($0.20); `update-todo-store` hit `round_limit` ($0.61); `delete-todo-endpoint` ended `needs_human`, the coder giving up after three "no commit" attempts ($0.75, the full cap). Cause of both failures: the planner invented a flag to retire a flag (`retire-update-todo-store-flag`, `retire-delete-flag`), the Orchestrator then told the coder to put the retirement behind it, and the coder and reviewer contradicted each other for four rounds. Even the success invented and released a junk flag (`retire-filter-flag`). Fixed locally (not pushed): the planner prompt and a validator rule say retiring a flag is internal (no flag), the coder prompt allows "no flag", and two reviewer fixtures (a correct retirement is clean; re-gating a live route behind a new flag is blocked) pass 4/4.
- Still to decide here: the retirement itself leaves the old flag in GrowthBook (never archived), and the three runs together left `ojones-todo` with junk flags `retire-filter-flag` (released, a no-op) and `retire-delete-flag` (never released, so DELETE is dark in production; see ticket 11).
- Confirmation (2026-10-12), after the planner/coder/reviewer fixes (e749dad): three more retirement Update Intakes (`retire-delete-flag`, `retire-filter-flag`, `patch-todo-endpoint`) were queued together, all three ran in order and **all three succeeded** in one round each ($0.10, $0.12, $0.17), each planned as `flag: null, internal_only: true`, outcome `nothing_to_release`. The app's `flags.json` ended with only its two heartbeat flags, DELETE came back to life, and every endpoint answered correctly. The retired flags were then archived in GrowthBook by hand (`POST archived=true`, as `teardown.sh` does) after confirming only comments mentioned them. Open: archiving is still a manual step; a retirement run should do it, or the digest should list retired-but-not-archived flags.

## Resolution (2026-10-13)

Decided with the owner: a flag has one job (stage a change dark, release it when safe), is short-lived, and is never used by hand. Retirement is automatic under standing owner approval (STANDARDS-FEATURE-FLAGS.md), through an Update Intake. A flag is retired when released (not switched off by the watchdog), still in `flags.json`, released on an earlier day, and a later Build Run also ended `released`; a `nothing_to_release` run counts for nothing; the newest release keeps its flag. Flags are built to be removed (one per change set, one entry point, a string literal; coder prompt and reviewer rubric). A flag the watchdog switched off is dead: the fix removes it and delivers the corrected change behind a new flag. The run rejects a coder commit that still references the slug, ends clean if the flag is already gone, and archives the removed flags in GrowthBook. Built in `orchestrator/flag_retirement.py` (INV-37). Proven live on `ojones-todo`. Not done: a deterministic codemod for retirement (the Agent path succeeded at $0.10 to $0.36); add one if retirements start failing. Off flags that are not watchdog-off need no rule, because only the pipeline switches flags.

## Change (2026-10-13): retirement rides along

The owner did not want runs spent on retirement. The daily pass and its workflow were removed: a proven flag is now retired inside the next Update Intake's Build Run for the same app, up to five at once so a backlog clears. Same eligibility rules, same guards and archiving.

## Change (2026-10-13): one story, one flag

A failed feature is retried on its own issue with the same flag instead of a new fix request and a new flag. A comment says it broke and why; the retry state is hidden in it; the planner must reuse the flag; the release step switches the story's own flag back on once the fix passes; after two retries the issue stays open (needs-human), attached to its flag. Issue and flag also name each other (label, title tag, GrowthBook description and tag, State link).
