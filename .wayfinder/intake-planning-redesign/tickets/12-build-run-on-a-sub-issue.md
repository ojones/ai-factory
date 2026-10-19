---
title: Build Run domain: run on a sub-issue and refuse the unplanned
type: task
status: open
assignee:
blocked_by: [09-planning-plan-contract.md, 10-retrospective-domain.md, 11-build-run-split.md]
---

## Question

Change Build to run on a GitHub sub-issue, using the shape ticket 01 verified. A Build Run is started for a child (a sub-issue of a New App Intake or Update App Intake parent, STEP 2.5, 6.3, 7.4). Decide and build: (a) how the run finds its parent and siblings from the sub-issues API (the child's parent, then the parent's sub-issues) instead of the `plan:<parent>` label, the title, or an in-memory plan; (b) what it reads from the child itself: the issue body (the complete coding instructions) and its `factory-plan` marker (`kind`, `flag`, `flag_story`, `internal_only`, `requirements`, `depends_on`), and nothing from the planner's earlier output; (c) what it does with the parent: only reads its number for the `Intake: <factory>#<parent>` marker, the App State record and comments, never its body as instructions; (d) refusing a child that is not a sub-issue of any parent, or has no marker ("not planned yet"), and the invariant "`proceed-with-change` is only put on a sub-issue whose body has a `factory-plan` marker"; (e) the secrets check reads the marker the planner wrote; a `kind: staging` child is a first build; no automatic retry is started from here. Unit test each rule with mocked `gh`, including a child with no parent, a child with no marker, a child whose parent has since closed, and a fix child whose `flag_story` is not its own number.

## Added context

Source plan: "Changes 4", now read through sub-issues ("Changes 2"). Sub-issues have no dependency field of their own, so `depends_on` stays in the marker (check in ticket 01 whether GitHub's separate issue-dependency feature is available; if it is, record whether to use it instead). Replace a lookup of the parent by label or title only where this group did it; the Retrospective domain (ticket 10) owns listing siblings and advancing, and the Build Run domain asks it for the parent and siblings rather than calling `gh` itself, so the sub-issue shape is known in one place. Does not yet remove `plan_change`; that is ticket 13. Re-point INV-48 once the planner owns the first `awaiting_secret`.
