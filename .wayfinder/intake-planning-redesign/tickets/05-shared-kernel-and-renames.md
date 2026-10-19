---
title: Create shared/ and the folder mechanics
type: task
status: resolved
assignee: ojones
blocked_by: [04-decide-the-domain-layout.md]
---

## Question

Behaviour-preserving. (1) Create `orchestrator/shared/` with the modules ticket 04 decided: `github.py` (one `GitHub` client replacing the five copies of `gh` in `update_intake`, `fixrequest`, `production_feedback`, `retrospective` and `BuildRun`; labels with `ensure_label`; the PAT versus Actions-token choice), `agent_runner.py` (an `AgentRunner` from `Budget`, `invoke`, `agent_json`, `run_watched`, isolation self-check and spend metering in `build_run.py`, used by the planner, the retrospective Agent and the Build Run), `outcomes.py` (the one list of Build Run endings and which are good, answered or failed, replacing the mirrored tuples in `build_run`, `audit`, `appstate`, `dashboard`) and `config.py` (the `profiles.yml` and limits loader). Each is a small interface with its own tests. (2) Add the folder mechanics: an empty `__init__.py` in each folder, workflows that import from folders set `PYTHONPATH=orchestrator` and run `python -m <domain>.<command>`, `style_test.py` walks folders, and a new `boundary_test.py` enforces the import rules in the map's Notes (shared imports no domain; each domain imports `shared` and only the listed domain edges; no cycles). (3) Apply the rename in one mechanical commit: `intake` to `new-app-intake`, `update-intake` to `update-app-intake` (labels, forms, workflows, `update_intake.py` and its test, docs, GLOSSARY, invariants). `ready-for-staging` stays until the Staging ticket.

## Added context

Decided in ticket 04: domains are plain Python folders; `shared/` (not `tools`) holds what two or more domains use; `child_tickets.py` joins `shared/` in the Planning contract ticket, where the marker is defined. Source plan: "Changes 5" (rename part). Create the new GitHub labels with `ensure_label` and say what happens to open issues carrying the old names; check every workflow `if:` that matches a label string. Green before and after: `ruff check` and the full unit suite. No behaviour change.

## Resolution (2026-10-19)

Scope reduced: the Agent runtime and the renames were too large and too risky to do in the same commit, so they are now tickets 05b and 05c. What this ticket did, behaviour unchanged, `ruff check` clean, 494 tests OK (3 skipped), every flat module still imports when run as a script:

- **Folder mechanics.** `orchestrator/shared/` with an empty `__init__.py`; test discovery finds its tests; flat scripts import it with no `PYTHONPATH` change (the script directory is already on the path). `style_test` now walks folders. New `boundary_test.py` holds the import rules of the map (shared imports no domain or flat module; each domain imports `shared`, itself and its allowed edges; the allowed graph has no cycle; every folder is a domain or `shared`); checked that it fails when `shared` imports `build_run`.
- **`shared/outcomes.py`** (`OK`, `ANSWERED`, `PROVIDER_BLOCKED`, `WATCHDOG_DISABLED`, `is_ok`, `is_answered`): the one list of endings, replacing the copies in `build_run`, `audit`, `appstate`, `dashboard` and the literal tuples in `retrospective`. INV-24's test now checks the modules use the one list, and a test fails if another module keeps its own copy. `appstate` keeps its slightly different "dark feature" exclusion (`refused`, `provider_blocked`, not `awaiting_secret`) as before.
- **`shared/config.py`** (`load`, `limits`): replaces `build_run.load_config`.
- **`shared/github.py`** (`run`, `ensure_label`): replaces the copies of `gh` in `update_intake` and `fixrequest` and `update_intake.ensure_label`; callers in `build_run`, `canary`, `benchmark`, `production_feedback`, `fly_audit` and `flag_retirement` use `github.ensure_label`. Tests patch `github.run` once instead of each module's `gh`.

**Left for the domain tickets** (each already touches the tests that mock them): the `gh` copies in `retrospective.py` and `production_feedback.py` and `benchmark.gh` (built on `build_run.sh`), `BuildRun.gh` and the inner `gh` in `build_run.py`, and the direct `b.sh(["gh", ...])` calls in `flag_retirement`, `fly_audit`, `maintenance` and `template_sync`. Each domain ticket replaces its own with `shared/github` (the Request, Pilot, Retrospective, Bugs, Flag Lifecycle and Build Run tickets). `shared/child_tickets.py` comes with the Planning contract (ticket 09).
