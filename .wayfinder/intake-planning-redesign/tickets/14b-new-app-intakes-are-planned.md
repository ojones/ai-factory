---
title: New App Intakes are planned
type: task
status: resolved
assignee: ojones
blocked_by: [14-staging-domain.md]
---

## Question

Make every New App Intake go through planning (STEP 1.1, 2.1 to 2.6, 3.1), the way Update App Intakes now do. `planning/plan_run.py` already supports a New App Intake (a first build, the first change set `kind: staging`, no flag, every later set depending on it) but `limits.plan_new_apps` is false, because until ticket 14 nothing stages a `kind: staging` child and the old `ready-for-staging` path still runs. When ticket 14 has made staging trigger on a staging child: turn `plan_new_apps` on (and retire the switch in the same commit if the live check passes), change the New App Intake form text (no `ready-for-staging`; submitting starts planning; the first child stages the app; moved here from ticket 14 so the text changes in the same commit that makes it true), and remove the old no-plan route for good: the `ready-for-staging` trigger in `app-staging.yml`, the legacy branch of `stage.sh`, the first-build Intake path in the Build Run (`identify_intake` for a title-named Intake) and every other `ready-for-staging` reference. Check and unit test: feasibility and the secret scan apply (INV-40), the first child is the staging child and the rest wait on it (blockers), the planner reads the spec alone because no repository exists yet, a refused or needs-human ending leaves the Intake re-plannable by removing and re-adding `new-app-intake`, the parent Intake closes with its last child, and `Intake: <factory>#<parent>` in the repo description names the parent (INV-22).

## Added context

Split out of ticket 14 so the shell and workflow work (staging on a child) lands and is proven before the planner is allowed to produce staging children for real apps. The flag `plan_new_apps` is a temporary switch (STANDARDS-FEATURE-FLAGS.md: short-lived, retired by riding along): ticket 17 must retire it. INV-22 and INV-40 move from "rows that change" to Built here. Live proof: one throwaway New App Intake end to end (plan, staging child, a business child, parent closed).

## Resolution (2026-10-19)

Done together with the removal of the app-wide kill switch and the other legacy paths, at the owner's request ("remove any logic or concept of the kill switch, and get rid of any legacy paths that are not in the latest diagram"). 660 tests OK (3 skipped), `ruff` clean. Not committed, not run live.

**New App Intakes are planned.** `limits.plan_new_apps` is gone: submitting a New App Intake always plans it (a first build: the first change set `kind: staging`, every later one depending on it). **Removed:** the `ready-for-staging` trigger in `app-staging.yml`, the whole legacy branch of `stage.sh` (it now stages a staging child only), the first-build Intake path of the Build Run (`identify_intake` accepts only a child ticket labelled `update-app-intake`, `update_intake`/`intake_kind`/`build_kind_from` are gone, a Build Run refuses a staging child, and `build_kind` is always `update`), the `plan:<parent>` label (the parent link is the sub-issue), and every `ready-for-staging` mention in docs, forms, the provider alert and the bench-app spec. The New App Intake form says submitting starts planning. `max_simultaneous_build_runs` stays.

**The app-wide kill switch is gone.** Starter: no `killSwitchKey`, no maintenance middleware in `app.ts` (health is mounted first), no kill-switch entry in the test provider, `with-flag.ts` or `preview.test.ts`; `AGENTS.md` says every change is flagged. `stage.sh` no longer creates `<app>.global-kill-switch`. Staging check `flag_round_trip` (which toggled it) is `flag_service`: GrowthBook has the app's own SDK connection, and a healthy deploy already shows the app reaches the service (it starts only once its flag provider is ready). Reviewer prompts and rubric, the reviewer smoke fixtures, the replay case, the coder smoke test, the tester smoke stub, STANDARDS-FEATURE-FLAGS (the "Mandatory kill switch" section and the "first build needs no flags" rule: staging needs no flag, every change set after it does), ARCHITECTURE, INV-16 and INV-57 are updated. Existing apps keep a harmless `global-kill-switch` flag in GrowthBook and get the Starter change through template sync (the coder merges `app.ts`).

**Kept on purpose, and why.**
- `limits.planner_enabled`: the stop for planning until ticket 17 proves it live (the map already retires it there).
- The automatic retry of an unchanged child (`fix_request.file_app_retry`, the retry state in comments): it is not in the diagram, but its replacement, the fix child, is ticket 15.
- The "first build" wording in the Agent prompts and the eval harnesses: dead for production runs, but they are the measurement of the Agents; new ticket [18b](18b-drop-first-build-from-prompts-and-harnesses.md) removes it with a before and after run.
- The benchmark still needs ticket 13b.
