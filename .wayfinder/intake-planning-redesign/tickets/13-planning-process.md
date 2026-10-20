---
title: Planning domain: planning becomes its own process
type: task
status: resolved
assignee: ojones
blocked_by: [12-build-run-on-a-sub-issue.md, 05b-extract-the-agent-runner.md]
---

## Question

Wire the Planning domain into `.github/workflows/plan.yml` (`issues: labeled`, job `if` on the two intake labels, `concurrency: plan-<issue>`, setup from `build-run.yml`, no Node/Fly/Playwright) with `plan_run` as a thin sequencer over the group's tested parts; endings `planned`, `refused`, `awaiting_secret`, needs-human, and retry by removing and re-adding the label. Then delete `plan_change`, the planner gate, the `planned` outcome and its mirrors (`audit.py`, `appstate.py`, `dashboard.py`, INV-24/25/26), audit rule A-06 and the planner from `check_models`. Automated sources file `update-app-intake` with the PAT and planning always files at least one child. Put it behind `limits.planner_enabled` until proven.

## Added context

Source plan: "Changes 1, 4, 5". Test the `plan.yml` trigger `if`, idempotency and each ending. Update the workflow count in `docs/orchestrator-map.md`. Open Intakes from before need re-labelling to be planned.

**Moved here from ticket 03:** change the Update Intake form text ("submitting starts planning"; no `proceed-with-change` on the parent) in the same commit that makes it true.

## Resolution (2026-10-19)

`ruff check` clean, 638 tests OK (3 skipped), `boundary_test` and `flow_spec_test` pass. Not committed. **Not run live.** This is the switch-over: after a push, the first Update App Intake exercises `plan.yml`, the sub-issue filing, the start gate and a Build Run on a child, in that order, none of which has run on GitHub yet. If planning misbehaves, `limits.planner_enabled: false` stops it (an Intake is then simply not planned), and reverting the commit restores the old path.

**What now exists.**
- **`.github/workflows/plan.yml`** (`issues: labeled`, job `if` on the two intake labels and not on a body carrying `factory-plan:` or a `benchmark` label; `concurrency: plan-<issue>`, not cancelled; setup copied from `build-run.yml`: OpenHands, the Agent account, the unit tests; no Node, Fly or Playwright). A child ticket carries the `update-app-intake` label, so without the marker guard each child would have been planned.
- **`planning/plan_run.py`**: `read_intake` (kind from the label, app, request, cap, secret scan, the target repo exists and is the Factory's) and `PlanRun`, the sequencer over the tested parts, with every outside thing handed in (the Agent, comments, secret names, ChildTickets, `file_children`). Endings: `planned` (always at least one child, even for one change set), `refused`, `awaiting_secret`, `needs_human`, `skipped` (a child, a non-Intake, or an Intake that already has children: no second planning and no spend). Every stop comments and says to remove the label and add it again. `main()` clones the app read-only for an update, mints a planner-only credential under `limits.planner_cost_cap_usd` (0.50), checks the daily cap and the planner model with its fallback, runs the planner as the Agent account when isolation is on, and records the spend in the ledger.
- **`planning/secrets_check.py`** (the secret-name check and the coder's secrets note, moved out of the Build Run). The Build Run keeps checking declared secrets at every start (INV-48 now describes both places); `AwaitingSecret` still ends a run as an answer.
- **Automated sources** now plan like any Intake: `file_update_app_intake` creates the issue with the PAT (its label at creation fires planning) and no longer adds `proceed-with-change`; template sync, maintenance, production feedback and approve-retire go through it. The Update App Intake form says submitting starts planning and how to plan again.

**Deleted.** `build_run/plan_change.py` and its tests; the planner gate in `run`; the planner from `check_models`; the `planned` outcome (`outcomes.OK` is `released`, `nothing_to_release`), audit rule A-06 and its mirrors in `run_audit`, the dashboard and the benchmark (now `outcomes.OK`); the `limits.require_plan` setting from ticket 12 (a Build Run on an unplanned update is always refused); INV-24/25/26/48 reworded, INV-56 added, INV-55 no longer conditional.

**Decisions and known gaps.**
- **New App Intakes are not planned yet.** `PlanRun` supports them (first build, staging first set), but `limits.plan_new_apps` is false, because nothing stages a `kind: staging` child until ticket 14, and the old `ready-for-staging` path still runs. Turning it on is ticket 14's commit.
- **The benchmark cannot run until reworked.** It files an `update-app-intake` issue and dispatches `build-run.yml` on it directly; that issue is not a planned child, so the Build Run now refuses it, and `plan.yml` skips its `benchmark` label so it does not spend on production planning. Reworking it to file a planned child (through the planner of the candidate branch) is needed before the next pass; `docs/benchmark-protocol.md` and the bench app spec still describe the old path.
- Open Intakes from before need their label removed and added again to be planned; there are none known to be waiting.
- The planner prompt still says "default to exactly one change set" from before; rollback-sized rules were added in ticket 09.

**Left for later.** Ticket 14 (staging child, `plan_new_apps` on, the `ready-for-staging` removal); ticket 15 (fix children); the benchmark rework.
