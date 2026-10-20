---
label: wayfinder:map
title: Planning becomes its own process, and the flow becomes the numbered spec
---

## Destination

Planning runs as its own process (`plan.yml`) the moment a `new-app-intake` or `update-app-intake` issue is labelled, and files child tickets (sub-issues) that are each a complete set of coding instructions sized to one feature flag; `proceed-with-change` only ever goes on a child whose body is complete. The flow diagram is the official, numbered spec (`docs/flow-spec.md`, stable step IDs) and the built system is walked against it. The orchestrator code is reorganised so each diagram group is its own package of purposefully named modules with its own unit tests, so any group can evolve alone. All changes made in the repo and proven live.

## Notes

- Execution override: tickets carry out the change as well as decide it. Each ticket leaves `main` green (`ruff check`, the full unit suite) and is committed and pushed on its own, because `main` runs the live Factory.
- Origin: [source-plan.md](source-plan.md) is the approved plan (names already substituted). Read it before picking a ticket; it holds the diagram, the step index, the decisions and the per-area changes. Where a ticket and the plan differ, the ticket's later resolution wins.
- Order of work (owner's instruction): specs and documentation first, so every doc describes the new workflow; then the code **domain by domain**, one process at a time, each domain tested in isolation with unit tests for every assumption that can be unit tested before the next domain starts.
- Domains (decided in ticket 04) are the diagram's groups, each a plain Python folder under `orchestrator/` (an empty `__init__.py`; nothing is installed or versioned): `request` (1), `planning` (2), `staging` (3), `build_run` (4), `flag_lifecycle` (5), `retrospective` (6, record and advance included), `try_fix` (7), `bugs` (8), plus `maintenance` (template sync, maintenance) and `monitoring` (audit, benchmark, canary, dashboard, fly audit) for work outside the request flow. `shared/` holds what two or more domains use: `github.py` (one client), `child_tickets.py` (the sub-issue model and `factory-plan` marker), `agent_runner.py`, `outcomes.py` (the one list of endings), `config.py`. New domains may be added later; the aim now is to get these right.
- Design for change: any domain may be iterated heavily later, by a person or by an agent working with one in the loop, so a domain's folder holds everything about its process. Each file is named for the one responsibility it has. Domains mostly run as separate workflows and talk through GitHub (the marker, labels, the App State record), not Python imports.
- Import rules (enforced by `boundary_test.py`): `shared` imports no domain; every domain may import `shared`; `planning`, `build_run`, `maintenance`, `bugs`, `flag_lifecycle` and `try_fix` may import `request`; `build_run` may import `flag_lifecycle`; `retrospective` may import `try_fix`; `try_fix` may import `planning`; `monitoring` imports only `request`; no cycles. A new edge is a deliberate edit to the test and `docs/orchestrator-map.md`.
- Entry points: a workflow sets `PYTHONPATH=orchestrator` and runs `python -m <domain>.<command>`, with command files named for the command. Tests stay beside the code, named for the behaviour they check; cross-cutting tests (`invariants_test`, `style_test`, `flow_spec_test`, `boundary_test`) stay at the top of `orchestrator/`. No re-export shims or old paths are left behind: a move edits its workflow's command in the same commit.
- Move first, then change: a move or split of existing code is its own commit with behaviour unchanged and the existing tests green; behaviour changes come after, in the domain's own ticket. `main` runs the live Factory.
- Style: no docstrings in Python (STANDARDS-CODING); a domain's purpose, files and interfaces are written in `docs/orchestrator-map.md` and `docs/flow-spec.md`, not in code. Test files are `name_test.py`.
- Names: `new-app-intake` and `update-app-intake` (labels), "New App Intake" and "Update App Intake" (prose). The repo-description marker `Intake: <factory>#<n>` keeps its name.
- `docs/flow-spec.md` is the only flow diagram. `docs/diagrams.md`, `docs/intake-cycle.md` and `docs/update-flow.md` were deleted (owner's instruction, 2026-10-19); draw a new diagram only when one is needed, and cite step IDs instead of redrawing the flow.
- Step IDs (`STEP 4.9`) are a public contract once docs cite them. Never renumber; add or retire.
- Unattended by default: planning, hand-off and fix-first are automatic and bounded; no review gates. Any temporary switch (ticket 13's `limits.planner_enabled`) is short-lived and retired by the ticket that proves it. See STANDARDS-FEATURE-FLAGS.md.
- Tracker: local markdown. Tickets in `tickets/`; `blocked_by` lists ticket filenames; claimed = assignee set. One ticket per session.
- Related: ARCHITECTURE.md, GLOSSARY.md, docs/orchestrator-map.md, docs/invariants.md, orchestrator/build_run.py, orchestrator/update_intake.py, orchestrator/planner.py, infra/app-staging/*, .github/workflows/*.

## Decisions so far

Decided with the owner before charting (detail in [source-plan.md](source-plan.md), "Decisions"):

- No `begin-planning` and no `ready-for-staging` label: planning starts when the intake label is applied.
- Parent link is GitHub native sub-issues, not the `plan:<n>` label.
- The first child of a new app is the staging child (infrastructure and verification first, no business logic, no flag); later children carry the business logic, one flag each.
- Hand-off is automatic and one child at a time; a failed child blocks its siblings.
- Fix first, never retry unchanged: an app cause files a fix child ahead of the failed one under the same flag; a factory cause goes to a learning PR; no cause is `needs-human`. Automatic retry is removed.
- Flags keep their lifecycle (one story, one flag, ride-along retirement); the slug is `issue-<n>`, created OFF by the Orchestrator at run start, with a Starter flag-off/flag-on test check.
- A bug after a validated release is a new `update-app-intake` + `bug`; before that, the same issue stays open.

Decided by tickets:

- [Verify the platform assumptions](tickets/01-verify-platform-assumptions.md): sub-issues API, native dependencies and labels-at-creation all work as assumed; native dependencies are the likely source of truth for order (readiness means checking each blocker's state, the count never drops); a parent never closes by itself, and a child can have only one parent.
- [Write the numbered flow spec](tickets/02-write-numbered-flow-spec.md): `docs/flow-spec.md` holds the diagram (47 steps) and index, `flow_spec_test.py` keeps IDs unique and every citation valid, and each invariant has a Step.
- [Documentation describes the new workflow](tickets/03-docs-describe-the-new-workflow.md): ARCHITECTURE, GLOSSARY, flag standards, invariants and the orchestrator map describe the target, marking Target versus Built today; the issue forms wait for the tickets that make them true.
- [Decide the domain layout](tickets/04-decide-the-domain-layout.md): ten domain folders plus `shared/`, the import rules, `python -m` entry points, pilot-first move order and the `build_run/` file split (see Notes).
- [Create shared/ and the folder mechanics](tickets/05-shared-kernel-and-renames.md): `shared/` exists with `outcomes`, `config` and `github`; `boundary_test` enforces the import rules; the Agent runner (05b) and the renames (05c) were split out of it.
- [Extract shared/agent_runner.py](tickets/05b-extract-the-agent-runner.md): the Agent runtime is out of `build_run.py` into `shared/` (`AgentRunner`, `json_output`, `Budget`, the provider and process helpers), tested alone.
- [Request domain](tickets/06-request-domain.md): `request/` holds the intake labels, form reading and writing, the factory-repo check and `file_update_app_intake`, which every automated source now files through.
- [Pilot: Maintenance and Monitoring domains](tickets/07-pilot-maintenance-and-monitoring.md): the folder mechanics work (`python -m`, `PYTHONPATH`, test discovery, `boundary_test`); `audit.py` waits for Retrospective, and `monitoring` may import `request`.
- [Flag Lifecycle domain](tickets/08-flag-lifecycle-domain.md): `flag_lifecycle/` holds the flag state machine (manifest, story link, release, watchdog, retirement, dark feature); the deterministic slug and creation (08b) and the Starter flag-off/on check (08c) were split out.
- [Flag named after its issue](tickets/08b-deterministic-flag-name-and-creation.md): a plan says `flag: true`, the Orchestrator names the flag `issue-<n>`, creates it off and records it in `flags.json` before the coder starts, and release switches on only what the run created (plus the retried story's own flag).
- [Flag tests and retirement](tickets/08c-dark-mode-is-unit-tested-and-retirement-removes-tests.md): the Starter's `npm run check` runs `scripts/check-flags.mjs` (a flag needs a `withFlag` off and on test, one entry point), `withFlag` is a test helper, and the retirement verifier and coder prompt remove the tests too; template sync follows once.
- [Planning domain: the plan and the child contract](tickets/09-planning-plan-contract.md): `planning/` holds the plan gate (size S or M, at most 6 criteria, staging first for a new app, declared dependencies), the child bodies and idempotent all-or-nothing sub-issue filing; `shared/child_tickets.py` holds the marker and `ChildTickets`; native blockers are the source of truth for order.
- [Retrospective domain](tickets/10-retrospective-domain.md): `retrospective/` holds finalize, the retrospective split by step, advance by blockers (a stalled child holds its siblings), the parent closing with its last child and the named cause; rollback, spend ledger and prompts moved to `shared/`, `fixrequest` to `try_fix/`.
- [Build Run domain: split](tickets/11-build-run-split.md): `build_run.py` is the `build_run/` folder (one file per step, `run.py` sequencing, `start_build.py` the gate); `BuildRun` is mixins over shared state, so deeper decoupling is still open; tests split to the code they check.
- [Build Run on a sub-issue](tickets/12-build-run-on-a-sub-issue.md): a run finds its plan through the sub-issues API, reads only the parent's number and state, and refuses an unplanned child (no marker, no parent, other or closed plan) at the gate and in the run, behind `limits.require_plan` (off until plan.yml); a fix child names the failed story's flag.
- [Planning becomes its own process](tickets/13-planning-process.md): `plan.yml` + `planning/plan_run.py` plan an Update App Intake into at least one child ticket (endings planned, refused, awaiting_secret, needs_human, skipped); `plan_change`, the `planned` outcome and `require_plan` are gone; automated sources plan like any Intake; New App Intakes wait for `plan_new_apps` (ticket 14); the benchmark needs reworking.
- [Staging domain](tickets/14-staging-domain.md): `staging/` reads a `kind: staging` child and verifies the seeded app with six deterministic checks (no Agent, no Build Run for the staging child); `stage.sh` has a child mode and a dry run beside the legacy path; the legacy path, the form text and `plan_new_apps` moved to the new ticket 14b.
- [New App Intakes are planned](tickets/14b-new-app-intakes-are-planned.md): New App Intakes are always planned, the legacy `ready-for-staging` path, the first-build Build Run path, the `plan:<parent>` label and the app-wide kill switch are removed; the staging check is now the flag-service connection; the first-build wording in prompts and eval harnesses waits for ticket 18b.
- [Apply the intake renames](tickets/05c-apply-the-renames.md): `new-app-intake` and `update-app-intake` in code, forms, workflows and docs, ready in the working tree; the two GitHub labels must be renamed (not before the owner agrees) just before the push.

## Not yet specified

- The bound on fix attempts for one story before `needs-human` (ticket 15).
- Exact function-by-function moves for `build_run.py` and `retrospective.py` (tickets 10 and 11, tests first).
- A codemod that retires a flag mechanically (today the coder edits, a verifier rejects leftovers).
- What happens to open Intakes that predate the change (they have no children and must be re-labelled; whether to sweep them automatically).
- Whether the planner for a new app needs its own benchmark fixtures beyond the three new cases in ticket 09 (see [Benchmark files planned children](tickets/13b-benchmark-files-planned-children.md)).
- Retiring `limits.planner_enabled` once ticket 13 is proven live (ticket 17).

## Out of scope

- Changing the flag lifecycle itself (retirement rules, soak time, `approve-retire`), beyond naming and test checks.
- Parallel children (one child at a time stays, INV-23).
