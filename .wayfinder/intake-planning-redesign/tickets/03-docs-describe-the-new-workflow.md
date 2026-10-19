---
title: Documentation describes the new workflow
type: task
status: resolved
assignee: ojones
blocked_by: [02-write-numbered-flow-spec.md]
---

## Question

Bring every document in line with the new workflow before any code moves, using the final names (`new-app-intake`, `update-app-intake`, "New App Intake", "Update App Intake") and citing step IDs: ARCHITECTURE.md, GLOSSARY.md, `docs/orchestrator-map.md` (organised by group, with each group's purpose, intended files and interfaces; mark which parts are planned, not built), `docs/invariants.md` (Step column; rows that change under the new flow flagged), `docs/golden-intakes.md`, the issue-form text ("submitting starts planning") and `STANDARDS-FEATURE-FLAGS.md` (slug `issue-<n>`).

## Added context

Source plan: "Changes 7" and the Decisions. Docs only, so `main` stays green, but docs will describe behaviour the code does not yet have; each doc says so until the group ticket that builds it lands, and that ticket removes the note. `docs/diagrams.md`, `docs/intake-cycle.md` and `docs/update-flow.md` are already deleted; do not recreate them, cite `docs/flow-spec.md` step IDs instead. Commit the currently untracked `docs/orchestrator-map.md` (rewrite it by group; check its two diagrams, which are module and workflow maps, are still wanted). Use the repo's no-docstrings rule: the module map in docs is where a group's design is written down.

## Resolution (2026-10-19)

Docs only; `ruff check` and the full unit suite pass. Not committed.

- **ARCHITECTURE.md:** a "The flow" paragraph pointing at the spec and defining the markers **Target** (not built, tickets in this map) and **Built today**. Updated: the Planner role (STEP 2.1), the Coder's source, **Fix first** (replaces the Fix requests passage: fix child with the same flag, learning-PR resume, `needs-human`, no unchanged retry; today's retry kept under Built today), Dark features, Flag stories (slug `issue-<n>`, created at run start, flag-off and flag-on test check), Intake triage and Secrets (planning, both kinds), Learning loop item 3, and App Staging idempotency and handoff. The **Intake** section is rewritten for the target: New App Intake and Update App Intake, planning on label, idempotent, refused or stopped or planned, sub-issue child tickets with the marker, rollback-sized change sets, the staging child, automatic one-at-a-time hand-off, native dependencies, the parent closed by the Orchestrator, plus a Built today block with the current labels.
- **GLOSSARY.md:** Intake, New App Intake, Update App Intake (Update Intake kept as the former term), Planning, Child ticket, Staging child, Fix child, Flow spec, Flag slug; Dark feature and Fix request updated.
- **STANDARDS-FEATURE-FLAGS.md:** a "Target lifecycle" block (name, creation at run start, dark-mode tests, retirement removes tests, fix child keeps the flag, bugs after release).
- **docs/invariants.md:** a "Rows that change with the new flow" table naming, per affected INV, what changes and which ticket updates the row and its test. `flow_spec_test.py` now reads only the main table.
- **docs/orchestrator-map.md:** rewritten by group (modules today, what is planned, cross-group imports, workflows by trigger), with no diagrams; it is tracked from now on.
- **docs/golden-intakes.md:** both kinds are planned; wording follows.

**Deviations.** (1) The issue forms are not changed: the form is live, and the new text (submitting starts planning) is false until tickets 13 and 14 build it, so those tickets now carry the change. (2) The bound on fix attempts is not set by the plan; the docs say it is decided in ticket 15, which now lists it as an open decision. (3) Labels in Target passages use the final names while workflows and forms still use the old ones; Built today passages use the old ones.
