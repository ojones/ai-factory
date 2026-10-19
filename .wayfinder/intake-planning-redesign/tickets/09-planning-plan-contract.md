---
title: Planning domain: the plan and the child contract
type: task
status: resolved
assignee: ojones
blocked_by: [01-verify-platform-assumptions.md, 08b-deterministic-flag-name-and-creation.md]
---

## Question

Build the Planning domain's (`planning/`) pure parts and test every assumption in isolation: the plan schema and `validate_plan` (size `S`/`M`, `L` rejected, about 6 criteria per set, first set of a new app is `kind: staging`, existing rules kept), the `factory-plan` marker with its new fields (`kind`, `flag_story`, `size`, `depends_on`...), the rendering of a complete child body, the sub-issue filing calls (mocked `gh`, per ticket 01's findings), and idempotency (skip a parent that already has children). Update `agents/prompts/planner.md` (rollback-sized change sets; the planner no longer chooses a slug) and `agents/planner-fixtures/cases.json` (over-large set, set needing another's flag, new-app plan whose first set is not staging).

## Added context

Ticket 01 resolved: use native issue dependencies for `depends_on` (blockers listed and checked by state, never by count), create-then-POST for sub-issues, check the parent's list first, 422 means fail loudly. Decide here whether the marker also keeps a copy of `depends_on`.

Source plan: "Changes 2" and "Changes 6", the slug part of "Changes 10". The marker is the contract the Build, Retrospective and Try Fix domains read, so it is defined and tested here first and documented in `docs/orchestrator-map.md`. On a sub-issues API failure planning must fail loudly and never file orphans; unit test it. Nothing runs in the live workflow yet: the planner still runs inside the Build Run until the planning-process ticket.

This ticket also creates `shared/child_tickets.py`: a `ChildTickets` object for one parent holding the marker (parse and render), file a child, add a blocker, readiness from blocker states, and the parent lookup with its 404. The sub-issue shape lives only there; Planning writes it, Build Run, Retrospective and Try Fix use it. It also moves the existing plan, child and secrets parts of `update_intake.py` and `build_run.py` (`plan_meta`, `render_*`, `child_body`, `file_children`, `secrets_marker`) into `planning/`, behaviour unchanged first.

## Resolution (2026-10-19)

`ruff check` clean, 604 tests OK (3 skipped), `boundary_test` and `flow_spec_test` pass. Not committed. **Not run live**: filing now goes through sub-issues and blockers inside today's Build Run (`plan_change`), so the first multi-change-set update after the push is the proof; ticket 13 moves it into `plan.yml`.

**Moved first, behaviour unchanged** (all tests passed before the contract changed):
- `planner.py` is `planning/validate_plan.py` (its command line is gone: only tests and the Build Run used it); `triage.py` is `planning/triage.py` (its one test class that needs the Build Run and the retrospective is `refusal_test.py`, flat).
- From `update_intake.py`: `render_change_set_task`, `child_body`, `one_line` are `planning/render_child.py`; `render_plan_comment` is `planning/plan_comment.py`; `secrets_marker` and `declared_secrets` are `planning/secrets_marker.py`; `file_children` is `planning/file_children.py`. `update_intake.py` keeps `start`, `advance`, `ready_to_start`, `siblings` and the fix marker (they leave with the Build Run and Try Fix tickets).
- `plan_meta` and the `WAIT` label moved to `shared/child_tickets.py` as `read_marker` and `WAIT`; the flag slot `{{flag_slug}}` is `child_tickets.FLAG_SLOT` (`flag_slug.SLOT` points at it), so Planning does not import Flag Lifecycle. `build_run` may now import `planning` (a marked temporary edge in `boundary_test`, removed by ticket 13).

**The contract (changed):**
- **`shared/child_tickets.py`:** `marker_for`, `read_marker`, `render_marker`, `story_number` (the number a flag is named after: its own, or `flag_story` on a fix child), `ChildTickets` (`children`, `file`, `block`, `blockers`, `is_ready`, `withdraw`, `close`) and `parent_of` (a 404 is `None`, any other failure raises `ChildTicketError`). The calls are the ones ticket 01 observed: create the issue, add it by its numeric `id`, blockers by `issue_id`, readiness from each blocker's state. `shared/fake_issues.py` is the fake `gh` the tests use.
- **Marker fields:** `parent`, `cs`, `kind` (`staging` | `update`), `flag` (yes or no; the slug is always `issue-<n>`), `flag_story` (fix children only), `internal_only`, `size`, `requirements`, `secrets`, and `depends_on`. **Decision: native blockers are the source of truth for order.** The marker keeps `depends_on` (issue numbers) only as a temporary copy for the label-based `update_intake.advance`, and ticket 10 removes it when the Retrospective advances by blockers. Documented in `docs/orchestrator-map.md` (The child ticket contract).
- **`file_children`:** one sub-issue per change set with the complete instructions, dependencies as blockers, labels as before, first root started last. Idempotent (a parent that already has children returns them). All or nothing: a failure removes from the parent and closes the children made, then raises, because closing alone leaves a child listed and the parent would count as planned. Unit tested with failures at the link and at the blocker.
- **`validate_plan`:** `size` required, `S` or `M`, `L` rejected; at most `planner_max_criteria` (6, in `agents/profiles.yml`) criteria; `kind` (`staging` only on a first build, flag null); a first build's first change set is the only `staging` one and every later set depends on it; a change set that names another by id (title, criteria, verification) must list it in `depends_on`. That last rule is how "a set that only works while another's flag is on" is caught deterministically: dependents run after their dependency is released, so a declared dependency is safe and an undeclared one is rejected.
- **Planner prompt and fixtures:** rollback-sized slices, `size`, `kind`, the staging first set for a new app, additive data changes; five new cases in `agents/planner-fixtures/cases.json` (size L, too many criteria, needs another's flag, new app whose first set is not staging, and the good staging first set). INV-54 added with a test.

**Left for later.** The first-build planner and `plan.yml` (13); the Build Run reading `kind`, `flag` and `flag_story` from the marker, and refusing a child with no parent (12); advancing by blockers and dropping `depends_on` (10); a fix child's `flag_story` (15). `update_intake.start` still accepts an unplanned issue.
