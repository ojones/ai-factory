---
title: Verify the platform assumptions
type: task
status: resolved
assignee: ojones
blocked_by: []
---

## Question

Which platform behaviours does the plan rely on, and do they hold? Spike, no repo change. Check, in order: (1) the sub-issues REST shape with a read-only `gh api repos/ojones/ai-factory/issues/<n>/sub_issues` GET, then the create call (`POST .../issues/{n}/sub_issues` with the child's numeric `id`) on one throwaway issue; (2) whether `issues: labeled` fires for a label set by an issue form at creation (and whether `opened` also fires, so the planner must be idempotent); (3) the sub-issue read shapes the Build Run needs: the child's parent (`GET .../issues/{n}/parent`), the parent's list of sub-issues with their state, and what happens to them when the parent or a child is closed or reopened, plus whether GitHub's separate issue-dependency ("blocked by") feature exists on this repo and could replace `depends_on` in the marker; (4) whether an issue created and labelled with the PAT starts workflows, and one labelled with the Actions token does not.

## Added context

Source plan: "Changes 1, 2" and "Risks". Results can change tickets 05 to 08 (trigger shape, idempotency, which token files what). Record the observed payloads and any surprise in this ticket's resolution, and delete the throwaway issues. Free to run now; a throwaway issue is the only write.

## Resolution (2026-10-19)

Checked with read-only GETs on this repo, then one throwaway parent and two throwaway children (ai-factory #137 to #139, all deleted afterwards). Run with the owner's `gh` user token, not the Actions token.

**Sub-issues API (works as the plan assumed).**
- Add: `POST /repos/{o}/{r}/issues/{parent}/sub_issues` with `-F sub_issue_id=<numeric id of the child, not its number>`. Returns the parent. The child must exist first (create, then link).
- Read: `GET .../issues/{parent}/sub_issues` returns full issue objects in the order they were added, with `state`; `GET .../issues/{child}/parent` returns the parent, or **404 "No parent issue found"** for an issue with none (so "no parent" is a 404 to handle, not an empty body). The issue object also carries `sub_issues_summary` (`total`, `completed`, `percent_completed`) and `parent_issue_url`; the summary can lag a moment right after an add.
- A child can have only one parent and the same child cannot be added twice (422, "may not contain duplicate sub-issues and Sub issue may only have one parent"). So filing children is not idempotent by itself: the planner must check the parent's list first, as the plan says.
- Closing a parent does **not** close or detach its open children; the child keeps its parent link. Reopening the parent leaves the list as it was. So the parent never closes by itself, and "parent closes when the last child closes" (STEP 6.4) must be done by the Orchestrator. The summary's `completed` counts closed children.
- Events on the parent: `sub_issue_added` per child.

**Issue dependencies exist (decides ticket 12's open question).**
- `POST .../issues/{n}/dependencies/blocked_by -F issue_id=<numeric id of the blocker>` and `GET .../dependencies/blocked_by` work on this repo; the issue object has `issue_dependencies_summary` (`blocked_by`, `blocking`, `total_blocked_by`, `total_blocking`). An older issue here (#2) already uses it.
- **Gotcha:** closing the blocker does not reduce `blocked_by`; the count stays 1. Readiness must be computed by listing the blockers and checking each one's `state`, not by reading the count.
- Choice left to ticket 09 (the contract): use native dependencies for `depends_on` so the UI shows the order, and keep a copy in the marker only if a reader needs it without an API call. Recommended default: native dependencies are the source of truth, matching the map's "native blocking" preference.

**Events.**
- A label given at issue creation **does fire `issues: labeled`**. Creating the throwaway with `--label update-intake` (today's name) produced a `labeled` event and four runs at once (App Staging, Update Intake, Approve retirement, Factory Run), all skipped by their job-level `if`. Runs are created even when the job is skipped, so a skipped run is visible proof the event fired. Caveat: I created it through the API (what a form does server-side), not by submitting the web form itself.
- Whether `opened` also fires could not be seen, because no workflow here listens to it. The planner stays idempotent regardless (skip a parent that already has sub-issues), since a trigger on both events is possible later.
- A label set with a user token starts workflows (confirmed). That an Actions-token label starts none is documented by GitHub and relied on in `update-intake.yml`'s own comment; not re-tested, since it needs a pushed workflow. `FACTORY_PAT` exists as a repo secret (set 2026-10-08).

**Consequences for later tickets.**
- Ticket 09: sub-issue filing = create the issue, read its numeric `id`, POST it; check the parent's list first; fail loudly on 422 or any error and leave the parent re-plannable; add blockers with `blocked_by`; the marker need not carry `depends_on` if native dependencies are used.
- Ticket 10: advance by listing sub-issues, then for each waiting child list its blockers and check state; close the parent itself when `completed == total`.
- Ticket 12: handle the `/parent` 404 as "unplanned, refuse".
- Ticket 13: trigger on `labeled` only; idempotency by sub-issue list.
