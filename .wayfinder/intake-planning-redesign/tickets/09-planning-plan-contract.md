---
title: Planning domain: the plan and the child contract
type: task
status: open
assignee:
blocked_by: [01-verify-platform-assumptions.md, 07-pilot-maintenance-and-monitoring.md]
---

## Question

Build the Planning domain's (`planning/`) pure parts and test every assumption in isolation: the plan schema and `validate_plan` (size `S`/`M`, `L` rejected, about 6 criteria per set, first set of a new app is `kind: staging`, existing rules kept), the `factory-plan` marker with its new fields (`kind`, `flag_story`, `size`, `depends_on`...), the rendering of a complete child body, the sub-issue filing calls (mocked `gh`, per ticket 01's findings), and idempotency (skip a parent that already has children). Update `agents/prompts/planner.md` (rollback-sized change sets; the planner no longer chooses a slug) and `agents/planner-fixtures/cases.json` (over-large set, set needing another's flag, new-app plan whose first set is not staging).

## Added context

Ticket 01 resolved: use native issue dependencies for `depends_on` (blockers listed and checked by state, never by count), create-then-POST for sub-issues, check the parent's list first, 422 means fail loudly. Decide here whether the marker also keeps a copy of `depends_on`.

Source plan: "Changes 2" and "Changes 6", the slug part of "Changes 10". The marker is the contract the Build, Retrospective and Try Fix domains read, so it is defined and tested here first and documented in `docs/orchestrator-map.md`. On a sub-issues API failure planning must fail loudly and never file orphans; unit test it. Nothing runs in the live workflow yet: the planner still runs inside the Build Run until the planning-process ticket.

This ticket also creates `shared/child_tickets.py`: a `ChildTickets` object for one parent holding the marker (parse and render), file a child, add a blocker, readiness from blocker states, and the parent lookup with its 404. The sub-issue shape lives only there; Planning writes it, Build Run, Retrospective and Try Fix use it. It also moves the existing plan, child and secrets parts of `update_intake.py` and `build_run.py` (`plan_meta`, `render_*`, `child_body`, `file_children`, `secrets_marker`) into `planning/`, behaviour unchanged first.
