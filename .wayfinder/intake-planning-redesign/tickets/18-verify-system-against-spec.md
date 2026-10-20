---
title: Verify the system against the spec
type: task
status: open
assignee:
blocked_by: [17-live-proof.md]
---

## Question

Walk the step index in `docs/flow-spec.md`: for each step find the implementing module and the verifying test, invariant or live check, fill the "implemented by" and "verified by" columns, check `docs/orchestrator-map.md` matches the packages, and file every gap as a new ticket. Include the new steps 6.7 and 7.6 and the "From a failure to a fix" rules, and fill the invariants NEW-A, NEW-B, NEW-C into the numbered table with their tests.

## Added context

Source plan: "Changes 0" and "Verification" item 6. Last ticket; close the map when its gaps are ticketed or dismissed.
