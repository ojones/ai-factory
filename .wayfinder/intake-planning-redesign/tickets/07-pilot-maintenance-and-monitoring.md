---
title: Pilot: Maintenance and Monitoring domains
type: task
status: open
assignee:
blocked_by: [06-request-domain.md]
---

## Question

Move the lowest-risk code into domains first, to prove the folder mechanics on real workflows before anything in the request path moves: `maintenance/` (`template_sync`, `maintenance`) and `monitoring/` (`audit`, `benchmark`, `canary`, `dashboard`, `fly_audit`), each file split only where it already has two responsibilities, with tests beside the code. Each workflow's command changes in the same commit (`PYTHONPATH=orchestrator`, `python -m maintenance.template_sync`, and so on); no old path or re-export is left behind. `maintenance` imports `shared` and `request` only; `monitoring` imports no other domain (it reaches them through workflows). Run the full suite, `ruff check`, `boundary_test`, and one manual dispatch of a scheduled workflow that is cheap to run.

## Added context

Order decided in ticket 04: the pilot goes after `shared/` and Request because these files are scheduled or manual, nothing in the live request path depends on them, and they use `request` to file intakes. If the mechanics break, they break here. Update `docs/orchestrator-map.md` for the two domains. `canary.py` and `benchmark.py` import `build_run` and `update_intake` today; give them a narrow way to dispatch the Build Run workflow instead (the workflow is the interface) or note the import as a documented exception to remove in the Build Run ticket.
