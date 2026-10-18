---
title: Measure payoff: cost, rounds and review findings per accepted change
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

Several decisions were made without a number behind them: how much banding review findings by structure cuts rounds, whether the lint rules reduce findings, whether the pre-push review makes runs cheaper. There is no payoff metric yet (cost and rounds per accepted change, and the owner's intervention minutes), and the dashboard does not break out findings per run by category or rounds per run before and after a change. Define the metric, collect it from the Build Run Reports and State issues the Orchestrator already writes, and show it on the dashboard so a change to the pipeline can be judged against it.

## Added context

- It is the "payoff metric" on the map's not-yet-specified list, and the measure that ticket 14 (e) and ticket 15 (f) both ask for.
- Data that exists: `state.json` and the Report (rounds, stages, cost, blocking findings, `improvements`, `bugs`, outcome), the State and registry issues, `factory-data` on the dashboard, and the spend ledger. Reviewer findings now carry a `category` and `evidence_kind`, so findings by category can be counted.
- Only a handful of real runs exist, on one app, so start with the collection and a baseline, not thresholds.

## Resolution (2026-10-14)

Defined and built the collection and display; no thresholds, as the ticket asked. Unit-tested; the first real numbers appear on the next dashboard run.

- **The metric.** Per *accepted change* (a run that ended `released` or `nothing_to_release`): all spend over accepted runs (failed runs' cost is included, because it is the price of the accepted ones), all rounds over accepted runs, and blocking findings per run, overall and by category. The owner's intervention is counted as runs that ended needing a person (minutes of attention are not recorded anywhere, so they are not measured).
- **Before and after.** Each number is shown for all runs and for the last 10 (`RECENT_RUNS`), so a pipeline change is judged against the runs just before it; nothing is compared automatically.
- **Findings by category.** The scoreboard now records each round's blocking findings by `category` (tester checks as `tester_check`), carried in the Report and summed per run into the dashboard history; rows from before this change have none.
- **Where.** `orchestrator/dashboard.py` (`payoff`, the "Payoff per accepted change" table, a digest line) and `scoreboard_entry` in `orchestrator/build_run.py`.
- **Unblocks** ticket 20 (calibration) once enough runs carry categories.
