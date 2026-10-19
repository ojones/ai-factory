---
title: Request domain
type: task
status: open
assignee:
blocked_by: [05c-apply-the-renames.md]
---

## Question

Make the Request domain (`request/`, STEP 1.1 to 1.3) a folder: read an owner's form (`form_section`, `app_name`, the task and cost-cap override from the issue body, the cost-cap ceiling check, INV-10), check that the target app is one this Factory created (`is_factory_repo`, the `Intake: <factory>#<n>` marker, INV-22), and file an Update App Intake with the PAT (one `file_intake` that every automated source uses: label, `app:<slug>` label, optional dedupe by fingerprint). The forms themselves stay YAML under `.github/ISSUE_TEMPLATE/`. Files named for what they do (for example `read_form.py`, `check_target_app.py`, `file_intake.py`). Moves existing code from `update_intake.py` and `build_run.py` (`parse_intake`), behaviour unchanged, and leaves the callers importing from `request`. Unit tests per function with mocked GitHub.

## Added context

Decided in ticket 04: Request is a domain of its own (owner's call), so group 1 has a home and Planning, Build Run, Maintenance, Bugs and Flag Lifecycle may import `request` for reading and filing intakes. Source plan: "Changes 5" (automated sources file with the PAT). The detectors (template sync, maintenance, production feedback, flag retirement) keep their own request text; only filing moves here.
