---
title: Factory Change: open decisions
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

The Factory Change requirements (now in [docs/flow-spec.md](../../../docs/flow-spec.md#factory-change-requirements)) and group 9 of the flow spec are drafted. Four decisions are open before anything is built.

- D1 Merge policy. Recommended: Tier 1 self-merges on green gates and smoke, protected by the circuit breaker (FC-51; this reverses the drop of ticket 01); Tier 2 always waits for a person. Needs INV-15 amended in the same change.
- D2 Separate Analyst, Coder and Reviewer roles, or one Coder plus the existing reviewer. Recommended: three roles, because the Analyst's failing-test step is the main protection against plausible but wrong fixes.
- D3 Trigger threshold: `promote_after_runs = 2` as for lessons, or act on first sighting for stuck runs. Recommended: same as lessons.
- D4 Is branch protection already on for ai-factory (`unit`, `starter`)? FC-40 depends on it.

## Decision

- D1 Tier 1 self-merges on green gates and smoke behind the circuit breaker (FC-51); Tier 2 waits for a person. INV-15 is amended when 9.9 is built.
- D2 No Analyst. The Planner (2.1, role `factory_planner`) plans the Intake and its children are filed as sub-issues (2.4); one Factory Coder writes the failing reproduction first when the ticket has none; the Orchestrator checks the ticket shape and that a named reproduction fails on main before any agent runs.
- D3 `promote_after_runs = 2`, as for lessons; a person can force one with `ready-for-factory-run`.
- D4 Branch protection was off; enabled 2026-10-21 on `main`: required checks `unit` and `starter`, branches up to date, admins not bound, no required reviews. FC-40 refuses to start if it is later turned off.
