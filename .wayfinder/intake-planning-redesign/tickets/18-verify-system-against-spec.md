---
title: Verify the system against the spec
type: task
status: resolved
assignee: ojones
blocked_by: [17-live-proof.md]
---

## Question

Walk the step index in `docs/flow-spec.md`: for each step find the implementing module and the verifying test, invariant or live check, fill the "implemented by" and "verified by" columns, check `docs/orchestrator-map.md` matches the packages, and file every gap as a new ticket. Include the new steps 6.7 and 7.6 and the "From a failure to a fix" rules, and fill the invariants NEW-A, NEW-B, NEW-C into the numbered table with their tests.

## Added context

Source plan: "Changes 0" and "Verification" item 6. Last ticket; close the map when its gaps are ticketed or dismissed.

## Resolution

Walked on 2026-10-20, after the new-app and half of the update live proof. `docs/flow-spec.md` now has "Implemented by" (the tickets) and "Verified by" (unit tests, invariants, and what was seen live on `factory-bench`) for every step, including 6.7 and 7.6; the invariants NEW-A, NEW-B and NEW-C became INV-58, INV-59 and INV-60 with tests when their tickets landed (ticket 15b, 15c, 16). `docs/orchestrator-map.md` was checked file by file against the packages: every non-test module is listed; it was missing `shared/model_call.py`, `prompts.py`, `spend_ledger.py`, `fake_issues.py` and `try_fix/file_events.py`, now added.

Gaps, ticketed: [the coder explores instead of coding](19-coder-explores-instead-of-coding.md) (a live finding), [test gaps for 4.8 and 2.6](20-test-gaps-found-by-the-spec-walk.md). Also found and fixed in passing: the child ticket text pointed the coder at the parent issue ("planned in #N"); it no longer does.

Not closed by this walk: the steps no live run has exercised (listed in ticket 17's progress and in the "Verified by" column as "no live ..."); re-walk those when ticket 17 finishes. Ticket 18b stays open: it changes prompts and their recorded cases together and needs paid before-and-after runs to measure.
