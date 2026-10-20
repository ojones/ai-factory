---
title: Staging domain
type: task
status: resolved
assignee: ojones
blocked_by: [13-planning-process.md]
---

## Question

Make the Staging domain (`staging/`, STEP 3.1 to 3.2) a folder that does: stage the app (repo from the Starter, Fly app, flag-service connection, `Intake: <factory>#<parent>` marker) and verify infrastructure (CI green, healthy deploy, flag round trip, Preview Token path, declared secrets, smoke test), triggered by `proceed-with-change` on a `kind: staging` child instead of `ready-for-staging`. `app-staging.yml` and `stage.sh` change accordingly; `stage.sh` comments the repo link on the parent instead of closing it; the one-app-through-staging check counts open staging children in progress. Remove every `ready-for-staging` reference. Unit test everything that is not shell (the staging checklist, the concurrency count, trigger conditions); test `stage.sh` with a dry-run mode where possible.

## Added context

Source plan: "Changes 3". Riskiest ticket; consider splitting the shell and workflow part from the Python part. The planner's staging child body is produced by the Planning domain (ticket 09); this ticket owns what staging does with it.

**Moved here from ticket 03:** change the New App Intake form text (no `ready-for-staging`; submitting starts planning; the first child stages the app) in the same commit that makes it true. Also rename `Handoff` and `Idempotency` wording in ARCHITECTURE.md's Deployment provisioning section from the Target notes to plain statements.

## Resolution (2026-10-19)

`ruff check` clean, 660 tests OK (3 skipped), `boundary_test` and `flow_spec_test` pass, `bash -n stage.sh` passes and the dry run is tested against a fake `gh`. Not committed. **Not run live, and it is unreachable until ticket 14b**: a staging child exists only once a New App Intake is planned (`limits.plan_new_apps`, off). The legacy `ready-for-staging` path is untouched and still the only way a new app is made today. Two tickets were added for what this one does not do: [New App Intakes are planned](14b-new-app-intakes-are-planned.md) (turn planning on for new apps, remove the legacy path and the form text) and [Benchmark files planned children](13b-benchmark-files-planned-children.md).

**What was built.**
- **`staging/read_staging_child.py`** (STEP 3.1): reads the child and its parent through the sub-issues API and decides whether it may be staged now. It must be a `kind: staging` child of an open Intake whose marker names that Intake; the app comes from the child's form, the request and cost cap from the parent (for INTAKE.md; the only place a parent's body is read), at most `max_simultaneous_build_runs` apps in staging and Build Runs together (the old count of `ready-for-staging` Intakes is now "other open staging children with the start label"). It prints shell-quoted `KEY=value` lines (a request cannot inject commands: tested) or the reason with exit status 3.
- **`staging/verify_infrastructure.py`** (STEP 3.2): six deterministic checks in order, each reported, all run even after a failure: `ci_green` (the seed commit's Test Gate, Build and Deploy to Fly), `deploy_healthy`, `flag_round_trip` (kill switch off takes the app to maintenance, on brings it back, always restored), `preview_token` (cookie for the right token only), `secrets_present` (the three staging sets plus the declared ones), `smoke`. Everything outside is handed in, so the failure cases are unit tested. **Decision:** no Agent judges staging and no Build Run is started for the staging child; the old plan had a Tester Agent exercise the app, but these checks are stronger and free. The flow spec says so.
- **`stage.sh` child mode** (`STAGING_CHILD`): validation and capacity come from the Python above, the repo marker names the parent (`Intake: <factory>#<parent>`, INV-22), after the seed push it runs the verification, comments the repo link on the parent (left open), and closes the child through `python -m retrospective.close_child close`, which starts the first business child. A failed check leaves the whole picture as a comment on the child and takes its start label off, so adding it again retries. `STAGING_DRY_RUN=1` reads and checks and changes nothing.
- **Workflows.** `app-staging.yml` also runs on `proceed-with-change` for an `update-app-intake` issue whose body has `"kind":"staging"`; `update-app-intake.yml` skips those, so a staging child is never started as a Build Run (INV-57, tested on both conditions). The `app-staging` concurrency group (one app at a time) is unchanged.
- **Also:** `build_kind_from` now treats a planned `kind: update` child as an update even when the repository holds only the seed commit, so the first business child of a new app is flagged like any later one. `close_child` gained the `close` command; `boundary_test` allows `staging` to import `request`.

**Moved to 14b (so text changes in the commit that makes it true).** The New App Intake form text and every remaining `ready-for-staging` reference. The ARCHITECTURE Deployment provisioning notes (Idempotency, Handoff) are now plain statements of the staging-child path.

**Left for later.** A real staging run (ticket 17); the `flag_round_trip` check toggles the app's own kill switch for up to a few minutes, so it must not run on an app that already serves users (it runs only on a brand-new app); the GrowthBook update call is the one the release step already uses, but not against the kill switch of a live app yet.
