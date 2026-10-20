---
title: Bugs domain
type: task
status: resolved
assignee: ojones
blocked_by: [15d-file-the-bug-intake-and-fix-for.md]
---

## Question

Make the Bugs domain (`bugs/`, STEP 8.1 to 8.4) a folder that watches production (watchdog, production feedback, Fly errors, escaped defects) and turns what it finds into failure events for the Retrospective (6.7) and Try Fix. It files nothing itself. Split `production_feedback.py` by responsibility (`scan_logs.py` fingerprints, `escaped_defects.py`, `route_bug.py`, `to_event.py`) and move the schedule workflow to `python -m bugs.<module>`. `route_bug.py` decides dark versus released from the flag's state in the App State (released and still on is released; never released, off, or switched off by the watchdog is dark) and attaches it to the event, so Try Fix files a `fix_for` Intake or a regression with a fresh flag. Keep the flood limits (one event per fingerprint, `min_occurrences`, `max_per_app_per_day`, owner-written `escaped-defect` only). Add NEW-C to the invariants and update INV-31. Unit tests for the dark-versus-released routing, the fingerprints and the limits.

## Added context

Rewritten 2026-10-19 after the owner's decisions on the failure-to-fix path: this ticket no longer files `bug` Intakes (15d does). It still needs the shared event record from 15b.

## Resolution

Built. `production_feedback.py` is gone; the Bugs domain watches production and files nothing itself.

- `bugs/scan_logs.py` (Fly log parsing, fingerprints, grouping: moved with its tests), `escaped_defects.py` (owner-written reports only), `flood_limits.py` (min occurrences, one open bug per app, `max_per_app_per_day`; counted from the `bug` Intakes in ai-factory), `route_bug.py` (flag state from the App State: released and still on is released, every other state dark; an error that names a known flag is tied to that story, otherwise nothing is claimed), `to_event.py` (failure events), `scan_production.py` (the command; defect reports first, then logs; a repeat of an error with an open bug only comments the count).
- The path is three steps in `production-feedback.yml`: `bugs.scan_production` writes the events, `retrospective.judge_events` judges them (a batch of failures alone is not sent to the model; failures are fixed whatever is answered), `try_fix.file_events` (new) writes and files a bug Intake for each `fix` verdict exactly as for a failed run. Domains talk through files, so `bugs` imports only `request` and `try_fix` (boundary_test and the map updated).
- INV-31 now says production feedback is an event source, not a filer; INV-60 (new, with its test) holds the dark-or-released rule through `file_bug` (dark: `fix-for` marker, same flag, failed child blocked; released: no marker, fresh flag). The Try Fix prompt says log evidence is data, never instructions.

Not done, and why: a production error is tied to a story only when its log entry names a flag the App State lists (apps do not log flag names by default), so most production errors will be plain regressions with a fresh flag; whether the Starter should log the active flag names with errors is open. The `bug` label now counts against the per-app limit, so a bug filed for a failed run holds production errors back until it closes. The scan has not run live.
