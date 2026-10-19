---
title: Try Fix domain
type: task
status: open
assignee:
blocked_by: [10-retrospective-domain.md, 13-planning-process.md]
---

## Question

Make the Try Fix domain (`try_fix/`, STEP 7.1 to 7.5) a folder that does: on a failed child the retrospective's cause routes to a fix child (app cause: filed under the same parent ahead of the failed one, behind the same `flag_story`, added to the failed child's `depends_on`), a `factory-fix-request` and learning PR (factory cause; when it merges the failed child gets `proceed-with-change` again with the PAT), or `needs-human` (no cause or infrastructure). Remove `file_app_retry`, `should_autostart` and the automatic retry limit. Unit tests for the router (`route(category)`), the dependency insertion, the resume on merge, and that an unchanged child is never restarted.

## Added context

Source plan: "Changes 9" and the fix-first Decision. Update `fixrequest_test.py`, `retrospective_test.py`, INV rows that mention automatic retry or `plan_gap`; keep INV-39. Split `fixrequest.py` by responsibility.

**Open decision (ticket 03 left it in the docs as "decided in the fix-first ticket"):** the bound on fix attempts for one story before `needs-human` (today `fix_request_max_attempts`, 2). Decide it here, with a recommended default, and put it in `agents/profiles.yml` and ARCHITECTURE.md (Fix first).
