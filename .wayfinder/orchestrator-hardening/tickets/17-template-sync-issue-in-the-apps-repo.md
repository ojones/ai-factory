---
title: Should template sync also file an issue in each Managed App's own repo?
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

The owner said the template sync job should create a bug issue in each Managed App for what the new style guide and template report, and the Update Intake should pick it up, plan it and release it like everything else. Template sync already files an Update Intake per behind app in ai-factory, and the lint and formatter config now arrives at the start of that run with the coder fixing the violations, so that Intake was taken as the work item and no second issue was added. Is the extra record in the app's own repo wanted, what would it carry (the rules that changed, the violation count, a link to the Intake), who closes it, and how does it avoid becoming a second source of truth?

## Added context

- Where it stands: [15-style-guide-and-lint-agent.md](15-style-guide-and-lint-agent.md), Resolution (d), records this as a reading that may need correcting.
- If wanted, it is a small addition to `orchestrator/template_sync.py` after `file_intake`: an issue in the app's repo (labelled so production feedback does not turn it into a second Intake), linked from the sync Intake and closed by it when the run finishes; the duplicate check in the retrospective applies.
- Considerations: one more thing to keep in step; value is visibility in the app's own backlog and State issue. Nothing depends on it.

## Resolution (2026-10-14)

Decided with the owner: **no second issue.** Template sync keeps filing one Update Intake per behind app in ai-factory, and that Intake is the record and the work item: it carries the changed rules and the diff, the coder fixes the violations, and the Build Run releases them like any other change. Nothing is added to the apps' repos.

Why: a mirror in the app's repo would be a second source of truth to open, link and close, and nothing depends on it. The app's own repo still shows the sync in its history (the commit that brings in the lint and formatter config), and the Intake links to the run. The owner's earlier wording ("bug issues in each Managed App") is read as "a work item per app that the Update Intake picks up", which the Intake already is. Revisit only if the owner wants to see sync work from inside an app's repo alone.

No code or documentation changes.
