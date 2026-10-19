---
title: Retrospective domain
type: task
status: open
assignee:
blocked_by: [09-planning-plan-contract.md, 05b-extract-the-agent-runner.md]
---

## Question

Make the Retrospective domain (`retrospective/`, STEP 6.1 to 6.6; record and advance included) a folder that does: close a child, finalize and the retrospective (kept running after every run), advance to the next waiting child whose dependencies are closed (children listed through the sub-issues API, one at a time, INV-23), close the parent when the last child closes (STEP 6.4, new), the App State record, and the ongoing-signals hook (6.6). Split `update_intake.py`, `finalize`, `retrospective.py` and `appstate.py` by responsibility. Unit tests per step 6.1 to 6.6 with mocked GitHub: dependency gating, failed child blocks siblings, parent closes only on the last child, retrospective names the cause.

## Added context

Source plan: "Changes 2" (siblings, ready_to_start, advance), "Changes 3" (parent closes). The retrospective gains its cause output here (consumed by the Fix-first ticket); it does not yet file a fix child. Keep the `planned` outcome mirrors in step (INV-24) until the planning-process ticket removes them.

Also split the 873-line `retrospective.py` into files along its steps (for example lessons, minor findings and improvements, the Agent run and learning PR, the story report), and take `finalize`, `finish_update_intake`, `update_intake.advance` and the run summary rendering out of `build_run.py` and `update_intake.py`. Retrospective may import `try_fix` (route the cause) once that domain exists; until then it keeps calling `fixrequest`.
