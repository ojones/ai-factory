---
title: Bugs domain
type: task
status: open
assignee:
blocked_by: [13-planning-process.md]
---

## Question

Make the Bugs domain (`bugs/`, STEP 8.1 to 8.4) a folder that does: watch production (watchdog, production feedback, Fly errors, escaped defects), decide dark versus validated from the App State flag state, and route: a bug while the flag is dark or off appends to the same open story (STEP 8.1), a bug after a validated release files a new `update-app-intake` labelled `bug` (8.4, new label via `ensure_label`). Split `production_feedback.py` by responsibility. Unit tests for the dark-versus-released routing and the bug filing with the PAT.

## Added context

Source plan: "Changes 9" (bug label), "Changes 5" (automated sources file with the PAT). The other automated sources (template sync, maintenance) follow the placement decided in ticket 04.
