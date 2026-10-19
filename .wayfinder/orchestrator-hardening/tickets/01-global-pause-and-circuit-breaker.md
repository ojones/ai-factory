---
title: Global pause and circuit breaker
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

Everything the Orchestrator can stop today is per run (cost cap, time limit, review rounds) or per app (the kill switch). If something goes subtly wrong across many apps overnight, nothing stops all Build Runs and releases at once. What is the factory-wide pause, where does it live (a GrowthBook flag, a repo variable, a file the workflow reads first), what trips it automatically (N consecutive failed runs, a spend anomaly, a storm of watchdog disables), what exactly does "paused" block (new Build Runs, releases, App Staging, learning PRs), how is it cleared, and how does it double as a vacation mode?

## Added context

- The pre-mortem rows on spend runaway and shared single points of failure both end in "no one stops it".
- The post-release watchdog (decided: auto-disables a flag) needs a way to escalate when it keeps firing.
- Constraint: the check must not depend on the thing that may be failing (for example GrowthBook is shared and fails closed).
- Look at where a run starts: `.github/workflows/build-run.yml`, `app-staging.yml`, and the limits in `agents/profiles.yml`.
- Progress outside this ticket: a daily spend cap now exists (`limits.daily_cost_cap_usd`, read from a `factory-ledger` issue; ARCHITECTURE.md: Cost guardrails). It is one trip condition and one effect (refuse new runs), not the pause switch this ticket asks for. The post-release watchdog and `stuck_rounds` are per-run. Decide the global switch and its other trip rules here.
- Test bed: `ojones-todo` is a live app to try a pause against: once built, file an Update Intake with the factory paused and confirm no Build Run starts, then resume. The fast watchdog trips it produces are also a realistic input for the 'storm of watchdog disables' trip rule.
- Progress outside this ticket (2026-10-13): a model provider with no balance (HTTP 402) is now its own condition (`provider_blocked`, INV-29): a one-token preflight stops each Build Run before any work, and one alert asks for a top-up. It stops runs one at a time as they start; a factory-wide pause that also holds queued runs and Update Intakes while it lasts is still this ticket's job, and this is a natural first trip condition for it.

## Resolution (2026-10-14): not built

Dropped at the owner's call, after checking what the ticket was for. It came from the pre-mortem rows on spend runaway and shared single points of failure ("no one stops it") and from the picture of the Orchestrator running overnight across many apps. When it was written, nothing bounded spend across runs and a model provider with no balance was handled one failure at a time. Since then: the daily spend cap (`limits.daily_cost_cap_usd`, $10, refuses new runs), the per-run cap, the provider-balance preflight (`provider_blocked`, INV-29), one run at a time per app, the retry limit of 2, the per-app limit on production-feedback Intakes, the cap on open learning PRs, and flags that stay dark until a release passes. Money is therefore bounded at about $10 a day by code, and a bad release is bounded by the flag, the watchdog and the CI rollback of a regression. The cost-runaway case that motivated the ticket is covered, and the owner could not name a case where they would pull a switch.

What is left is convenience: one switch instead of a few commands. The automatic starters are known and few (three scheduled workflows and the label-started ones), so nothing was built (a short manual-stop document was written, then deleted on 2026-10-19 as unneeded). Not built: the pause flag, the trip rules (consecutive failures, a spend anomaly, a storm of watchdog disables) and the vacation mode, since no incident motivates them. **Revisit if:** the Factory manages many apps at once, a Factory change ever makes every app's run fail overnight, or the daily cap is raised enough that a runaway would matter.
