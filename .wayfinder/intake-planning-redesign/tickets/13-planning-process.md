---
title: Planning domain: planning becomes its own process
type: task
status: open
assignee:
blocked_by: [12-build-run-on-a-sub-issue.md, 05b-extract-the-agent-runner.md]
---

## Question

Wire the Planning domain into `.github/workflows/plan.yml` (`issues: labeled`, job `if` on the two intake labels, `concurrency: plan-<issue>`, setup from `build-run.yml`, no Node/Fly/Playwright) with `plan_run` as a thin sequencer over the group's tested parts; endings `planned`, `refused`, `awaiting_secret`, needs-human, and retry by removing and re-adding the label. Then delete `plan_change`, the planner gate, the `planned` outcome and its mirrors (`audit.py`, `appstate.py`, `dashboard.py`, INV-24/25/26), audit rule A-06 and the planner from `check_models`. Automated sources file `update-app-intake` with the PAT and planning always files at least one child. Put it behind `limits.planner_enabled` until proven.

## Added context

Source plan: "Changes 1, 4, 5". Test the `plan.yml` trigger `if`, idempotency and each ending. Update the workflow count in `docs/orchestrator-map.md`. Open Intakes from before need re-labelling to be planned.

**Moved here from ticket 03:** change the Update Intake form text ("submitting starts planning"; no `proceed-with-change` on the parent) in the same commit that makes it true.
