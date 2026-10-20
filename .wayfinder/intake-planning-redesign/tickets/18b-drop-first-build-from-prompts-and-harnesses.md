---
title: Drop the first-build concept from prompts and eval harnesses
type: task
status: open
assignee: ojones
blocked_by: [17-live-proof.md]
---

## Question

A Build Run is now always an update to an app that exists: the first child of a new app is staged and verified by App Staging (no Build Run), and every business child is built behind its own flag. The Build Run code no longer has a first-build path, but the Agent prompts and the evaluation harnesses still do: `{{build_kind}}` and the "first build" wording in `agents/prompts/coder.md`, `reviewer.md`, `reviewer-fast.md`, `reviewer-rubric.md`, `tester.md` and `planner.md` (the planner's own "first build" is the plan for a new app and stays), the `build_kind` field of `agents/replay/cases.json` (recorded real first-build reviews), `agents/smoke*/` tasks and fixtures, `agents/smoke/expected.json`, and the Report's `build_kind` field in `run_audit`, `app_state` and the dashboard. Remove them without losing the cases' value: re-record or re-label the replay cases as updates, rerun the reviewer smoke, the coder smoke and the coder replay (they cost money and change what the prompts are measured on), and take `build_kind` out of the placeholder tables in `shared/prompts_test.py`.

## Added context

Left out of the cleanup that removed the app-wide kill switch and the other legacy paths (ticket 14b) because these files are the measurement of the Agents: changing a prompt and its recorded cases together needs a before and after run, which belongs after the live proof, when the Update flow is known to work. Until then the prompts' first-build branches are dead for production runs and harmless.
