---
title: Write the numbered flow spec
type: task
status: resolved
assignee: ojones
blocked_by: []
---

## Question

Make the diagram official. Create `docs/flow-spec.md` with the Mermaid flow and the step index from the source plan (IDs stable, "implemented by" and "verified by" columns empty), add `flow_spec_test.py` (the Mermaid block parses to unique step IDs; every `STEP n.m` cited in `docs/*.md` and `docs/invariants.md` exists in the index), give the invariants table a `Step` column, and make `docs/intake-cycle.md` and `docs/update-flow.md` link to the spec instead of duplicating diagrams.

## Added context

Source plan: "Changes 0" and "The spec". Docs and a test only; no behaviour changes. Note `docs/intake-cycle.md` and `docs/orchestrator-map.md` are currently untracked in git; commit them as part of this. Use the final label names in the diagram (the source plan already does).

## Resolution (2026-10-19)

Built, not committed yet.

- `docs/flow-spec.md`: the status note, the groups, the rules for changing it, the Mermaid diagram (47 steps in 8 groups) and the step index (38 rows, ranges for 5.1 to 5.7 and 8.1 to 8.4) with empty "Implemented by" and "Verified by" columns. Taken from the source plan, so it already uses `new-app-intake` and `update-app-intake`.
- `orchestrator/flow_spec_test.py` (5 tests): each step is declared once and its label matches its node name; every edge names a declared step and every declared step is used; the eight groups exist; the index and the diagram list the same steps; every `STEP n.m` cited in `docs/*.md`, ARCHITECTURE.md and GLOSSARY.md exists; every invariant names an existing step. Checked it can fail by pointing an edge at a missing step. Full suite 481 tests OK (3 skipped), `ruff check` clean.
- `docs/invariants.md`: a Step column on all 50 rows, each pointing at the closest step (best effort; ticket 18 re-checks the mapping). The INV table test still matches because the ID regex ignores the new column.
- The older diagram docs (`docs/diagrams.md`, `docs/intake-cycle.md`, `docs/update-flow.md`) were deleted on the owner's instruction, so `docs/flow-spec.md` is the only flow diagram. `docs/orchestrator-map.md` stays (untracked) and is rewritten by ticket 03.
