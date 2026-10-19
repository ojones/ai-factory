---
title: Request domain
type: task
status: resolved
assignee: ojones
blocked_by: [05c-apply-the-renames.md]
---

## Question

Make the Request domain (`request/`, STEP 1.1 to 1.3) a folder: read an owner's form (`form_section`, `app_name`, the task and cost-cap override from the issue body, the cost-cap ceiling check, INV-10), check that the target app is one this Factory created (`is_factory_repo`, the `Intake: <factory>#<n>` marker, INV-22), and file an Update App Intake with the PAT (one `file_intake` that every automated source uses: label, `app:<slug>` label, optional dedupe by fingerprint). The forms themselves stay YAML under `.github/ISSUE_TEMPLATE/`. Files named for what they do (for example `read_form.py`, `check_target_app.py`, `file_intake.py`). Moves existing code from `update_intake.py` and `build_run.py` (`parse_intake`), behaviour unchanged, and leaves the callers importing from `request`. Unit tests per function with mocked GitHub.

## Added context

Decided in ticket 04: Request is a domain of its own (owner's call), so group 1 has a home and Planning, Build Run, Maintenance, Bugs and Flag Lifecycle may import `request` for reading and filing intakes. Source plan: "Changes 5" (automated sources file with the PAT). The detectors (template sync, maintenance, production feedback, flag retirement) keep their own request text; only filing moves here.

## Resolution (2026-10-19)

Behaviour unchanged except the small points below. `ruff check` clean, 518 tests OK (3 skipped; 12 new in `request/`), every flat module still imports as a script, `boundary_test` passes. Not committed.

**`orchestrator/request/`** (a folder with an empty `__init__.py`; imports only `shared`):
- `intake_labels.py`: `NEW_APP_INTAKE`, `UPDATE_APP_INTAKE`, `START` and `app_label`. They replace `update_intake.FORM_LABEL` and `update_intake.GO` everywhere. The module is not called `labels` because several modules already have a local variable of that name.
- `read_form.py`: `form_section`, `app_name`, `APP_RE` and `read_request(body, default_cap, ceiling)`, which raises `ValueError`. `build_run.parse_intake` stays as a four-line wrapper that turns the error into the Build Run's `NeedsHuman` stop.
- `render_form.py`: `form_body` (was `fixrequest.intake_form`).
- `check_target_app.py`: `is_factory_repo`.
- `file_intake.py`: `file_update_app_intake(repo, token, pat, app, title, request_text, source_label, source_label_desc, started_note, check)`: makes the labels, files the form-shaped issue, adds the start label with the PAT, posts the optional note, returns the number or None. It replaces `production_feedback.file_intake`, which maintenance and template sync called, and the hand-built filing in `flag_retirement.approve` (which passes `check=True`, so a failed call still raises).

**Small differences to know about.** The `app:<slug>` label is created with the description "Issues about the Managed App <slug>" by every source (production feedback used an empty description); it only shows when the label is first created. `flag_retirement.approve` now creates its label with the Actions-token argument set to the PAT, as before, through `github.run`.

**Tests.** The form, app-name and factory-repo tests moved out of `update_intake_test.py` into `request/read_form_test.py` and `check_target_app_test.py`; new tests cover the rendered body reading back, the cost-cap rules, and `file_update_app_intake` (labels and their order, the form body, the PAT adding the start label, the optional note, no number means nothing starts, `check`). `flag_retirement_test` now patches `github.run` for the filing.

**Left for later:** `identify_intake` stays in `build_run.py` (it reads the child and belongs to the Build Run's `read_child`, ticket 12); `update_intake.start` still validates the app with these helpers and moves to `build_run/start_build.py`.
