---
label: wayfinder:map
title: Make the Orchestrator safe to run unattended across many apps
---

## Destination

The Orchestrator can run overnight across many Managed Apps without a human watching, and the eight gaps below ("most likely to bite" from the pre-mortem) are each decided, with the adopted changes made in the repo.

## Notes

- Execution override: tickets may carry out the adopted change (edit docs, prompts, profiles, workflows, orchestrator code with tests) as part of resolving, not only decide.
- Origin: three advisory docs built on OpenHands' published posts (copies in `sources/`), then a pre-mortem and gap review. The full reasoning, pillars and phasing are in [source-plan.md](source-plan.md); read it before picking a ticket.
- The advice is advisory. Where it conflicts with ARCHITECTURE.md or the STANDARDS, the repo wins unless a ticket decides otherwise and says so.
- The change-set gate (a default-off flag per update) is the core of the test-in-production strategy. Judge every ticket by whether it keeps that gate trustworthy.
- Tracker: local markdown. Tickets in `tickets/`; `blocked_by` lists ticket filenames; claimed = assignee set. One ticket per session.
- Related: ARCHITECTURE.md, STANDARDS*.md, agents/profiles.yml, orchestrator/build_run.py, orchestrator/postmortem.py, .github/workflows/*, infra/app-staging/*.

## Decisions so far

- Update requests are ai-factory issues labelled `intake` + `app:<slug>`; the title stays the bare app name; state and outcomes stay in the app repo, with a registry issue in ai-factory for the cross-app view.
- A multi-change-set Intake runs as one Build Run per change set (the 6-hour Actions job limit rules out one run for all).
- Model drift is fixed in the docs: ARCHITECTURE.md follows `agents/profiles.yml` (DeepSeek-V4.1-Flash for coder and reviewer), and the shared-model risk against the "different lab" principle is recorded.
- Factory PRs from the learning loop auto-merge only for additive lint, formatter and Starter Template-default changes with all required checks green; everything else needs a human.
- The post-release watchdog may turn a flag off automatically on a health or error regression and opens a needs-human issue; the release step never re-enables it.
- The learning loop acts on the first occurrence, with lesson fixtures, required checks, recurrence tracking after merge and revert on "fix ineffective" as mandatory guardrails.
- A Managed App's third-party secret lives in a GitHub Actions secret on that app's repo, set by the owner with `gh secret set` and copied to Fly by the deploy job; a request that needs one stops after the planner as `awaiting_secret` until the names exist, then builds (ticket 13, decided and not built; a workflow_dispatch input is never used, it is not masked).
- What blocks a release is decided from the structure of a finding (category, evidence kind, a cited line or repro), not from the reviewer's label; checks that need no judgement are made by the Orchestrator; and only a tester check that failed costs the coder a round (ticket 14).
- The Starter's lint and formatter config is owned by the Orchestrator (the coder cannot loosen a rule); new rules come from the retrospective Agent, not a new role, and reach apps through the template-sync Update Intake, where only the coder fixes what they report (ticket 15).
- There is no factory-wide pause or circuit breaker (ticket 01, dropped): the daily and per-run caps, the provider-balance check and the per-app limits bound the damage, and `docs/stop-everything.md` is the manual stop. Revisit if many apps run at once or a Factory change breaks every app overnight.
- Monitoring starts as a data store plus a static dashboard (no new always-on service); a timeboxed OpenTelemetry spike checks whether the `openhands` CLI exports traces.
- The reworked pipeline and the isolated retrospective Agent are proven live (ticket 21): review-before-push, dark deploy then test, tags, labels and the retrospective on 2026-10-15; the Agent-user isolation and ACL carry-over on 2026-10-18 ($0.10). A learning PR, a release, the watchdog and a rollback were not seen.

## Follow-ups (tickets 16 to 29, all open)

Left over from the resolved tickets, saved so they are not lost: 16 build the secrets workflow, 17 whether template sync also files an issue in each app's repo, 18 recurrence counting, 19 the payoff metric and findings measure, 20 calibrate the review and lint rules (blocked by 19), 21 live proof of the reworked pipeline and the retrospective isolation, 22 live proof of the failure path, the rollback and approve-retire, 23 rerun the smoke fixtures under the new output shape, 24 the first whole-run benchmark baseline (when a model swap is pending). Added later: 25 separate round budgets for the pre-push review and the deployed test, 26 deterministic checks before the reviewer, 27 planner accuracy, 28 a lint rule for tests that assert nothing. 29 keep every Build Run under $1.

## Not yet specified

- The plan's larger pillars, to ticket once the eight gaps are decided: the gate record and criteria scoreboard, learning loop v2 and the Factory Run, assurance (design invariants, stub-LLM canary run, run auditor, dashboard), multi-app parallelism, and the planner stage.
- Failed unflagged runs staying live, flag-retirement behaviour and the other findings of the `ojones-todo` tests are in tickets 05 and 11.
- Prompt injection from content: only owner-authored Intake text and comments should reach Agents, especially on public repos.
- App growth: the single-call reviewer falls back past 200k characters, `AGENTS.md` accretes, cost and peak context rise as apps get bigger.
- Data and backups: backup and restore for apps with persistent state (the migration rule covers schema, not recovery).
- Code rollback: a deterministic "revert to the previous SHA" path for ungated changes.
- A payoff metric: cost and owner intervention minutes per accepted change.
- Owner ergonomics: phone notifications, one-tap approve or rollback, one morning digest.

## Out of scope

- Staged rollout (tester cohort, then percentage ramp), Schemathesis and RESTler tooling, until a measured gap or an OpenAPI schema exists. (Playwright and axe-core moved into scope as ticket 12 once the tester benchmark showed the API-side gap.) Revisit by redrawing the destination.
