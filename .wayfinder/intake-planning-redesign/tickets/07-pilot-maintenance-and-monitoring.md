---
title: Pilot: Maintenance and Monitoring domains
type: task
status: resolved
assignee: ojones
blocked_by: [06-request-domain.md]
---

## Question

Move the lowest-risk code into domains first, to prove the folder mechanics on real workflows before anything in the request path moves: `maintenance/` (`template_sync`, `maintenance`) and `monitoring/` (`audit`, `benchmark`, `canary`, `dashboard`, `fly_audit`), each file split only where it already has two responsibilities, with tests beside the code. Each workflow's command changes in the same commit (`PYTHONPATH=orchestrator`, `python -m maintenance.template_sync`, and so on); no old path or re-export is left behind. `maintenance` imports `shared` and `request` only; `monitoring` imports no other domain (it reaches them through workflows). Run the full suite, `ruff check`, `boundary_test`, and one manual dispatch of a scheduled workflow that is cheap to run.

## Added context

Order decided in ticket 04: the pilot goes after `shared/` and Request because these files are scheduled or manual, nothing in the live request path depends on them, and they use `request` to file intakes. If the mechanics break, they break here. Update `docs/orchestrator-map.md` for the two domains. `canary.py` and `benchmark.py` import `build_run` and `update_intake` today; give them a narrow way to dispatch the Build Run workflow instead (the workflow is the interface) or note the import as a documented exception to remove in the Build Run ticket.

## Resolution (2026-10-19)

Behaviour unchanged. `ruff check` clean, 518 tests OK (3 skipped), `boundary_test` passes, and each entry point starts (`PYTHONPATH=orchestrator python -m monitoring.canary`, `maintenance.template_sync` and `monitoring.dashboard` reach their own environment checks). Not committed. **Not yet run by GitHub:** the six workflows below changed their command; a manual dispatch of one cheap scheduled workflow (the Fly audit or the dashboard) is the live proof still to do.

**Moved (git renames, tests with them).**
- `maintenance/`: `template_sync.py`, and `dependency_updates.py` (was `maintenance.py`, renamed because a file called `maintenance` inside `maintenance/` says nothing).
- `monitoring/`: `benchmark.py`, `canary.py`, `dashboard.py`, `fly_audit.py`.
- Workflows now run `PYTHONPATH=orchestrator python -m <domain>.<module>`: `template-sync.yml`, `maintenance.yml`, `fly-audit.yml`, `canary.yml`, `benchmark.yml` and `dashboard.yml` (which uses `factory/orchestrator`). Comments, ARCHITECTURE.md, `agents/profiles.yml`, `agents/benchmark/*` and `docs/benchmark-protocol.md` follow. No old path or shim is left.

**What the move forced into `shared/` and `request/`** (each was used by a pilot file and by a flat module, and a domain may not import a flat one):
- `shared/shell.py` (`sh`), `shared/starter_template.py` (the protected and orchestrator-owned template files and `protected_violations`), `shared/preview_token.py` (`for_app`), `shared/github.git_auth_env`, `shared/config.FACTORY_DIR` and `GROWTHBOOK_API`.
- `shared/app_state_record.py`: the App State record's format (`load`, `dump`, the two labels) and `managed_apps`, the list of Managed Apps from the registry issue. `appstate.py` keeps the rendering and uses it.
- `shared/api_check.py` (moved from `orchestrator/api_check.py`, with its test): the tester's HTTP check helper, which the benchmark also uses to score a task. It is stdlib only and still copied into the run's tools directory.
- `request/find_intakes.py`: `intakes_with` (was in `production_feedback`).

**Decisions made along the way.**
- `monitoring` may import `request` (benchmark files its issues in the form's shape; fly audit checks the factory marker). The rule changed from "imports no domain"; `boundary_test`, the map and the docs say so.
- `audit.py` stays flat for now: `finalize` calls it in the Build Run's process, so it moves with `finalize` into Retrospective (ticket 10), not into `monitoring`.
- Tests that sat in the wrong file moved: the ledger tests to `build_run_test.py` and the flag-key test to a new `flag_set_test.py`.

**Left for later.** `dashboard.py` and the others still read `outcomes` from `shared`; nothing else crosses. Live proof of the six renamed workflow commands is the first dispatch after the push.
