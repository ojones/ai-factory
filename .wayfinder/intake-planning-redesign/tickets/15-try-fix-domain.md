---
title: Try Fix domain
type: task
status: resolved
assignee: ojones
blocked_by: [10-retrospective-domain.md, 13-planning-process.md]
---

## Question

Make the Try Fix domain (`try_fix/`, STEP 7.1 to 7.5) a folder that does: on a failed child the retrospective's cause routes to a fix child (app cause: filed under the same parent ahead of the failed one, behind the same `flag_story`, added to the failed child's `depends_on`), a `factory-fix-request` and learning PR (factory cause; when it merges the failed child gets `proceed-with-change` again with the PAT), or `needs-human` (no cause or infrastructure). Remove `file_app_retry`, `should_autostart` and the automatic retry limit. Unit tests for the router (`route(category)`), the dependency insertion, the resume on merge, and that an unchanged child is never restarted.

## Added context

Source plan: "Changes 9" and the fix-first Decision. Update `fixrequest_test.py`, `retrospective_test.py`, INV rows that mention automatic retry or `plan_gap`; keep INV-39. Split `fixrequest.py` by responsibility.

**Open decision (ticket 03 left it in the docs as "decided in the fix-first ticket"):** the bound on fix attempts for one story before `needs-human` (today `fix_request_max_attempts`, 2). Decide it here, with a recommended default, and put it in `agents/profiles.yml` and ARCHITECTURE.md (Fix first).

## Resolution (2026-10-19)

`ruff check` clean, 666 tests OK (3 skipped), `boundary_test` and `flow_spec_test` pass. Not committed. **Not run live**: the first failed child after the push exercises it.

**Decision: the bound is `fix_attempts_max: 2` fix children per story** (`agents/profiles.yml`, replacing `fix_request_max_attempts` and `fix_request_autostart`). Two because the first fix often meets a second problem the failure hid, while a third attempt at the same story is the model repeating itself. Counted among the parent's children by `flag_story` and `fix_for`, so a fix of a fix counts against the same story. After it the failed child is left `needs-human` and its siblings wait (the Retrospective's advance holds them).

**What it does (`try_fix/`, `fixrequest.py` is gone and split by responsibility):**
- **App cause** (`fix_child.py`): a fix child is filed under the same parent with complete instructions (what happened, the numbered requirements, how to approach it, then the failed change set's original instructions, never nested), `flag: true`, `flag_story` (the failed story's number, so its flag is `issue-<n>` of the original) and `fix_for`. The failed child is made blocked by it and given `waiting-on-plan`; the fix child is started with the PAT. The failed child itself is never started again as it was: it resumes through the normal advance when the fix closes. If GitHub refuses a step the fix child is taken back and the failed child is held for a person. The fix is built by the Orchestrator from the retrospective's facts, not by a planner Agent (cheaper, repeatable, and the requirements are already checkable).
- **Factory cause** (`factory_fix_request.py`, `resume_after_merge.py`, `resume-failed-child.yml`): one fix-request issue per failed child, and the learning PR names the child (`failed-child` marker, added by `learning_pr.propose` only when the cause routes to the Factory). The child is held `needs-human`; when the PR merges the workflow starts it again with the PAT. Auto-merged PRs now merge with the PAT in `factory-checks.yml`, because a merge by the Actions token starts no workflow.
- **No cause or infrastructure** (`needs_human.py`): an information issue and the child held until the owner edits it and adds `proceed-with-change` again.
- **Removed:** `file_app_retry`, `should_autostart`, `retry_decision`, the retry state and `fix_meta` markers, `reuse_flags` and `retry_state` in the Build Run and the planner check (a fix child names its flag from its marker), the `retrying` label. `route.py` keeps the cause rules (`inferred_category`, `route`). The Build Run reads `fix_for` and tells the reviewer and tester the flag is the failed story's (`fix_child.fix_note`).
- INV-26, 27 and 39 reworded; tests per module (`route`, `failure_text`, `fix_child` including the attempt bound, the dependency order, a refusal part way, and that the failed child is never started; `file_failure`, `factory_fix_request`, `resume_after_merge` including the workflow conditions).

**Left for later.** The live proof (ticket 17); a fix child that fails for the same reason twice still costs two builds before a person sees it (the bound is the only brake); a Factory fix only resumes a child when the Agent opened a PR in that same retrospective (a cause named by a person later, with no PR, leaves the child held).
