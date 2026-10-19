---
title: Decide the domain layout and interfaces
type: grilling
status: resolved
assignee: ojones
blocked_by: [03-docs-describe-the-new-workflow.md]
---

## Question

How is `orchestrator/` reorganised so each diagram group is a package that can evolve alone? Decide with the owner: (a) the packages and the file names inside each, one responsibility per file, from the current modules (`build_run.py` 2617 lines, `update_intake.py`, `fixrequest.py`, `retrospective.py`, `production_feedback.py`, `flag_retirement.py`, `flag_set.py`, `planner.py`, `triage.py`, `appstate.py`...); (b) the shared kernel (GitHub calls, labels, `factory-plan` marker, limits and profiles, secrets, ledger) and what it may not contain; (c) the interfaces between groups (what the marker, labels and App State record promise) and the rule that a group does not reach into another's internals, ideally checked by a test; (d) where Request (group 1) and the automated sources (1.3) live; (e) how tests are laid out so a group's tests run alone (`python3 -m unittest discover` per package) and still all run together; (f) the order in which groups are extracted, and how workflows and `python3 orchestrator/x.py` entry points keep working through each move.

## Added context

Context: files today are flat in `orchestrator/` with tests beside them as `name_test.py`; workflows call modules by path. The decision is recorded in this ticket and the target layout is written into `docs/orchestrator-map.md`. Prefer many small, purposeful modules over one per group; prefer no re-export shims left behind. Ask the owner for a recommended layout first (do not present an exhaustive survey). Re-order or add tickets 05 to 17 if the layout changes the sequence.

## Resolution (2026-10-19)

Grilled with the owner over three rounds. Facts first: `orchestrator/` was flat with no folders; every workflow ran `python orchestrator/<file>.py`; the `gh` wrapper was copy-pasted in five modules; `build_run.py` (2,617 lines) held the Agent runtime, planning, flag release, finalize and fix-first; the good-endings list was mirrored in four modules (INV-24).

**Decided.**
- **Vocabulary.** The diagram's groups are **domains**; each is a plain Python folder (an empty `__init__.py`, nothing installed or versioned). "Package" was only ever meant as "folder". Added to the GLOSSARY with **Shared**.
- **Domains (ten).** `request` (1, its own domain by the owner's call), `planning` (2), `staging` (3), `build_run` (4; `build_run` and not `build`, which is also a pip package), `flag_lifecycle` (5), `retrospective` (6, record and advance included), `try_fix` (7; renamed from "first fix"), `bugs` (8), plus `maintenance` (template sync, maintenance) and `monitoring` (audit, benchmark, canary, dashboard, fly audit).
- **`shared/`** (the owner prefers it to `tools`): `github.py`, `agent_runner.py`, `outcomes.py`, `config.py`, and `child_tickets.py` (the sub-issue model, built with the Planning contract). It imports no domain.
- **Import rules**, checked by `boundary_test.py`: every domain may import `shared`; `planning`, `build_run`, `maintenance`, `bugs`, `flag_lifecycle` and `try_fix` may import `request`; `build_run` may import `flag_lifecycle`; `retrospective` may import `try_fix`; `try_fix` may import `planning`; `monitoring` imports no domain; no cycles. Domains mostly talk through GitHub (marker, labels, App State), not imports.
- **Entry points** `PYTHONPATH=orchestrator` and `python -m <domain>.<command>`; tests beside the code, named for the behaviour; cross-cutting tests stay at the top; no shims or old paths, the workflow command changes in the same commit.
- **Order**: `shared/` and the renames, then Request, then a pilot of the low-risk Maintenance and Monitoring domains (to prove the mechanics), then Flag Lifecycle, the Planning contract, Retrospective, the Build Run split, Build Run on sub-issues, the planning process, Staging, Try Fix, Bugs.
- **`build_run/` file split** (names in ticket 11).

**Done in this session.** Tickets renumbered to 18 (new: 06 Request domain, 07 the pilot), tickets 05 and 08 to 16 reworded for domains, the map's Notes and Decisions updated, `docs/orchestrator-map.md` rewritten as the target layout, `docs/flow-spec.md` and the GLOSSARY use "domain", and the Invariants table's ticket column was remapped.

**Left open.** Exact function-by-function moves for `build_run.py` and `retrospective.py` (tickets 10 and 11, tests first); the fix-attempt bound (ticket 15). No ADR written: the choice is reversible (it is folders).
