---
title: Build Run domain: run on a sub-issue and refuse the unplanned
type: task
status: resolved
assignee: ojones
blocked_by: [09-planning-plan-contract.md, 10-retrospective-domain.md, 11-build-run-split.md]
---

## Question

Change Build to run on a GitHub sub-issue, using the shape ticket 01 verified. A Build Run is started for a child (a sub-issue of a New App Intake or Update App Intake parent, STEP 2.5, 6.3, 7.4). Decide and build: (a) how the run finds its parent and siblings from the sub-issues API (the child's parent, then the parent's sub-issues) instead of the `plan:<parent>` label, the title, or an in-memory plan; (b) what it reads from the child itself: the issue body (the complete coding instructions) and its `factory-plan` marker (`kind`, `flag`, `flag_story`, `internal_only`, `requirements`, `depends_on`), and nothing from the planner's earlier output; (c) what it does with the parent: only reads its number for the `Intake: <factory>#<parent>` marker, the App State record and comments, never its body as instructions; (d) refusing a child that is not a sub-issue of any parent, or has no marker ("not planned yet"), and the invariant "`proceed-with-change` is only put on a sub-issue whose body has a `factory-plan` marker"; (e) the secrets check reads the marker the planner wrote; a `kind: staging` child is a first build; no automatic retry is started from here. Unit test each rule with mocked `gh`, including a child with no parent, a child with no marker, a child whose parent has since closed, and a fix child whose `flag_story` is not its own number.

## Added context

Source plan: "Changes 4", now read through sub-issues ("Changes 2"). Sub-issues have no dependency field of their own, so `depends_on` stays in the marker (check in ticket 01 whether GitHub's separate issue-dependency feature is available; if it is, record whether to use it instead). Replace a lookup of the parent by label or title only where this group did it; the Retrospective domain (ticket 10) owns listing siblings and advancing, and the Build Run domain asks it for the parent and siblings rather than calling `gh` itself, so the sub-issue shape is known in one place. Does not yet remove `plan_change`; that is ticket 13. Re-point INV-48 once the planner owns the first `awaiting_secret`.

## Resolution (2026-10-19)

`ruff check` clean, 627 tests OK (3 skipped), `boundary_test` and `flow_spec_test` pass. Not committed. **Not run live, and the refusal is off by default**: it sits behind `limits.require_plan` (false in `agents/profiles.yml`), because until `plan.yml` exists (ticket 13) an Update App Intake is still planned inside its own Build Run and has no marker or parent. Ticket 13 turns it on in the same commit that makes the planning process file every child. With it on, `proceed-with-change` on anything but a planned child is refused both at the gate and in the run.

**Decisions.**
- **(a) Finding the plan.** `child_tickets.parent_info` (new; `parent_of` uses it) asks the sub-issues API for the child's parent and returns `{number, state}`, or `None` for GitHub's 404. The Build Run asks `shared/child_tickets`, where the sub-issue shape lives, not the Retrospective domain (ticket 10 put it in `shared` so Build Run, Retrospective and Try Fix can all use it). No label or title is read for this.
- **(b) What the child supplies.** The body (the complete instructions) and the marker, nothing from a planner's earlier output. From the marker: `kind` (a `staging` child is a first build whatever the repository holds: `read_child.build_kind_from`), `flag_story` (a fix child's flag is `issue-<flag_story>`: `child_tickets.story_number` in `name_the_flag`, and a flag that already exists is never touched), the secrets (the check already read them there) and `flag`/`internal_only` through the task text the planner rendered. `depends_on` is gone from the marker (ticket 10); order is the blockers.
- **(c) The parent** is read for its number and state only, kept in the Report as `parent`; its body is never read as instructions.
- **(d) Refusal** (`read_child.planned_problem`, raised as `NeedsHuman` "not planned yet"): no marker; no parent; a marker naming a different parent than the sub-issue's real one; a parent that has since closed (a plan someone closed is not worked under; reopen it or file a new request). A lookup that fails is loud, never a silent pass. `prepare_run.locate_plan` runs this in `setup` for any child with a marker, and for any Update App Intake when `require_plan` is on; a New App Intake is never looked up. `start_build.start` applies the same rule before dispatching, so the invariant is "the start label does something only on a planned child" (INV-55).
- **(e)** No automatic retry starts from the Build Run (it never did; the retrospective's `fix_request` still does until ticket 15). `plan_change` stays, and a child with a marker already skips it.
- **GitHub dependencies:** ticket 01 found them available; ticket 10 made them the only record of order.

**Tests.** `LocatingThePlan` (child of an open plan reads only the number; no parent; closed parent; marker naming another plan; unplanned intake refused only when required; new app not looked up; failed lookup is loud; staging is a first build; fix child's `flag_story`), `RequiringAPlan` for the gate (planned child starts; no marker, no parent, closed, other plan each refused with the reason and nothing dispatched; off changes nothing; failed lookup refuses), INV-55 in `invariants_test`.

**Left for later.** Ticket 13 turns `require_plan` on and re-points INV-48 (the first `awaiting_secret`) to the planner; the "accepted" comment on a start still says the run plans the change until then; a staging child's trigger and labels are ticket 14.
