---
title: Flag Lifecycle domain
type: task
status: resolved
assignee: ojones
blocked_by: [07-pilot-maintenance-and-monitoring.md]
---

## Question

Make the Flag Lifecycle domain (`flag_lifecycle/`, STEP 5.1 to 5.7) a folder whose files each do one thing (for example slug, create, release, retire, verify) and make it deterministic: slug `issue-<n>` from the story number (unique by construction); an idempotent `ensure_feature` at the start of a run (production off, `flags.json` entry written before the coder starts); `release` only switches it on; the Starter `withFlag(slug, on, fn)` helper and an `npm run check` step that fails when a slug lacks a flag-off and a flag-on test or has more than one entry point (cases in `agents/lint-fixtures/cases.json`); the retirement verifier extended to tests and `flags.json`; ride-along selection, soak and `approve-retire` kept. Unit tests for every transition in the group's state machine (STEP 5.1 to 5.7).

## Added context

Source plan: "Changes 10". Update INV-39 and add "a flag's slug is `issue-<n>` of its story". Works on today's story issues, so it can land before the planner moves. The Build Run domain calls this domain only through its small interface (ensure, release, retire); `build_run.py` is edited just enough to call it, the split is the Build ticket.

## Resolution (2026-10-19)

Scope reduced to the move: the deterministic slug, `ensure_feature` and the Starter check change behaviour, so they are tickets **08b** and **08c** (ticket 11, the Build Run split, now waits for them; ticket 09 waits for 08b so the planner stops choosing slugs once). `ruff check` clean, 541 tests OK (3 skipped; 23 new), `boundary_test` passes, every flat module still imports as a script, and the two entry points start (`python -m flag_lifecycle.set_flag` and `approve_retire`). Not committed. **Not yet run by GitHub:** the commands of `flag-set.yml` and `approve-retire.yml`.

**`orchestrator/flag_lifecycle/`** (imports only `shared` and `request`; `flag_retirement.py` and `flag_set.py` are gone):
- `flag_manifest.py`: `SLUG_RE`, `manifest_slugs`, `removed_flag_slugs`, `new_flag_slugs`, `feature_key`.
- `story_link.py`: `flag_label`, `title_with_flags`, `flag_description`, `flag_tags`, and `link` (the label, title tag and comment on the story; was `BuildRun.link_flags_to_issue`'s body).
- `release_features.py`: `release_flags` (create a new flag on, switch the retried story's own flag back on, leave every other flag alone; was `BuildRun.release`'s body).
- `watchdog.py`: `count_errors`, `watchdog_trip`, `disable_flags`, `watch` (the loop; was `watch_release`'s).
- `retirement_selection.py`: which flags ride along (`candidates`, `piggyback_slugs`, `app_flags`, `choose`) and the coder and tester text; carries the design comment of the old `flag_retirement.py`.
- `retirement_check.py`: the `retire-flag:` lines and the "no code may mention the slug" verifier. `retirement_archive.py`: archive the removed flags in GrowthBook.
- `dark_feature.py`: `is_dark_broken`, `label_dark_feature`, the `approve-retire` rules and the removal request. `approve_retire.py`: the workflow's command. `set_flag.py`: the by-hand switch (`python -m flag_lifecycle.set_flag`). `fake_growthbook.py`: an in-memory GrowthBook for tests.
- **Build Run side:** `BuildRun.release`, `watch_release`, `disable_flags`, `link_flags_to_issue`, `archive_retired_flags` and `choose_flags_to_retire` stay as short methods that pass their own state in and write the result back (tests that replace them keep working). `flag_findings` (the reviewer's flag checks) stays in the review.

**Tests.** The old `flag_retirement_test.py` split by file (`retirement_selection_test`, `retirement_check_test`, `dark_feature_test`, `approve_retire_test`); the pure flag, watchdog and story-link tests moved out of `build_run_test.py`; new tests cover `release_flags`, `watch` and `disable_flags`, `link`, `archive_removed`, `set_flag.main`, and `lifecycle_test.py` walks one flag through STEP 5.1 to 5.7 on the fake GrowthBook (dark, released, eligible, retired; switched off by the watchdog and released again by the story's retry; a dark feature a person approves).

**Changed commands.** `flag-set.yml`: `PYTHONPATH=orchestrator python -m flag_lifecycle.set_flag "$APP" "$FLAG" "$STATE"`; `approve-retire.yml`: `... python -m flag_lifecycle.approve_retire approve <issue>`. Docs: the orchestrator map and the flow spec's code column.
