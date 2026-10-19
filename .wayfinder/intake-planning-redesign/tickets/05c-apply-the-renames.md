---
title: Apply the intake renames
type: task
status: resolved
assignee: ojones
blocked_by: [05-shared-kernel-and-renames.md]
---

## Question

One mechanical commit: the `intake` label becomes `new-app-intake` and `update-intake` becomes `update-app-intake` (labels in code, the two issue forms and their file names, `.github/workflows/update-intake.yml`, `app-staging.yml` and `stage.sh`, `identify_intake`/`parse_intake`, `update_intake.py` constants such as `FORM_LABEL`, `agents/benchmark/*`, `docs/golden-intakes.md`, GLOSSARY, ARCHITECTURE (Built today passages), invariants and tests). Prose becomes "New App Intake" and "Update App Intake". The `Intake: <factory>#<n>` repo marker keeps its name. `ready-for-staging` stays until the Staging ticket. Create the new GitHub labels with `ensure_label`, say what happens to open issues and registry rows that carry the old names, and check every workflow `if:` that matches a label string. Do not rename `update_intake.py` itself: its contents move into the Request, Planning, Build Run and Retrospective domains in later tickets.

## Added context

Split out of ticket 05 on 2026-10-19 because it touches live label matching in workflows; do it in a quiet moment and verify with one dispatch. Source plan: "Changes 5" (rename part) and the Naming override. Green before and after: `ruff check` and the full unit suite.

## Resolution (2026-10-19)

Done in the working tree; `ruff check` clean, 494 tests OK (3 skipped), every workflow and form parses, `stage.sh` passes `bash -n`. Not committed, and **not live until the GitHub labels are renamed (below)**.

- **Labels in code:** `intake` is `new-app-intake` (`app-staging.yml` condition and comments, `stage.sh`'s three `--label` queries, the New App Intake form); `update-intake` is `update-app-intake` (`update_intake.FORM_LABEL`, `flag_retirement`, the workflow condition, the form, tests, docs).
- **Files:** `.github/ISSUE_TEMPLATE/intake.yml` is `new-app-intake.yml`; `update-intake.yml` is `update-app-intake.yml`; `.github/workflows/update-intake.yml` is `update-app-intake.yml` (workflow name "Update App Intake").
- **Prose:** "Update Intake" is "Update App Intake" in code, comments, docs, prompts, workflows' comments and `agents/profiles.yml` comments. "Intake" on its own stays the umbrella term. The Built today passages in ARCHITECTURE.md and the GLOSSARY use the new names.
- **Not changed on purpose:** `templates/starter/` (two comments say "Update Intake"; changing them would make template sync file an Intake for every app), `docs/advice/`, the `update_intake.py` module name (its contents move to other domains later), the `Intake: <factory>#<n>` repo marker, the form field headings the body parser reads, and `ready-for-staging`.
- **Found and fixed:** the Update App Intake form did not parse as YAML (an unquoted `: ` in the description, present before this ticket), so GitHub may have been rejecting it. Quoted.

**Before the push (live, waiting for the owner's go-ahead):** rename the two labels on the repo so existing issues and the registry keep them, then push straight after. Order matters: the Factory creates a missing label itself (`ensure_label`), and a label that already exists under the new name would block the rename.

```bash
gh label edit update-intake --name update-app-intake -R ojones/ai-factory
gh label edit intake --name new-app-intake -R ojones/ai-factory
```

Between the rename and the push, the old workflows on `main` will not match, so do not leave a gap and do it while no Build Run is in flight. Not yet exercised live: a new issue from each renamed form; one cheap proof is to open a throwaway `new-app-intake` issue (it starts nothing without `ready-for-staging`) and check the `App Staging` run is created and skipped.
