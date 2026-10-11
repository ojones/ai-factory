# Adoption of the advice

Status per recommendation: **done** (already true), **adopt** (we will do it as written), **adapt** (we will do it differently, reason given), **defer** (right idea, wait for evidence), **reject** (does not fit). "Where" points to the doc or code that carries it, or the ticket that will.

## Process and planning

| Recommendation | Status | Notes / where |
|---|---|---|
| Work directly on `main`, no feature branches, one writer at a time | done | `STANDARDS-CODING.md` (Git workflow); the coder is the only Agent whose work reaches `main`. Factory PRs (learning loop) are the one exception and apply to this repo, not to Managed Apps. |
| Read-only discovery and review may run in parallel | done | Reviewer and tester run at the same time. |
| Inspect before designing; never invent paths or commands | done | `coder.md`, reviewer and tester prompts read the repo and `AGENTS.md`. |
| Define verification before coding starts | adapt | Acceptance criteria (`AC-n`) per change set are planned; today the Intake is free text. Ticket: Intake triage and criteria. |
| Stable requirement IDs and traceability | adapt | Kept in a per-app App State issue, not a file on `main` (a file would need an Orchestrator commit, redeploy on every change and break "only the coder reaches `main`"). |
| Decompose requirements into bounded GitHub issues (change sets) | adapt, partly done | Decided: one Build Run per change set, each with its own flag. The planner runs first in every Update Intake's Build Run (`limits.planner_enabled`); a plan of several change sets becomes one child Update Intake each, started in dependency order. First builds do not use it. |
| Dependency graph, acyclic, ready-only dispatch | adopt, partly done | The validator rejects cycles and orders change sets by dependency; children are started by `update_intake.advance` only when their dependencies are closed. |
| Plan validation gate before dispatch | adopt, partly done | `planner.py validate`: coverage, links, criteria, flags, limits; blocking questions exit as "needs a person". Runs before any coding in an Update Intake. |
| Ask the user about decisions that change scope, data or security | adapt | A Build Run is unattended, so the equivalent is a needs-human Issue in the app repo, and the owner confirming criteria before a larger build. |
| Agent handoff template (objective, scope, criteria, verification) | adapt | Prompts already carry task, round, findings; criteria and gate fields are added with the scoreboard work. |
| Keep issue status and dependencies current | adapt, done | App State issue per app and a registry issue in ai-factory, rewritten after every Build Run. |
| Issue-per-agent assignment | reject | We hand off through `main` and structured JSON files, not issues or PRs. |
| Parallel agents in isolated worktrees | reject | Conflicts with trunk-only. Parallelism is across apps, serial within an app. |

## Change-set gate and production testing

| Recommendation | Status | Notes / where |
|---|---|---|
| Default-off, server-enforced gate for a not-yet-trusted change set | done | The update's flag (`STANDARDS-FEATURE-FLAGS.md`); the Orchestrator releases it. |
| One gate per change set, not per feature; do not gate trusted changes by default | done | "A flag covers the change, not each route"; a first build needs none. |
| Treat gate enablement as a production change; deterministic release | done | The release step is not an Agent and checks four conditions for the pushed SHA. |
| Tester cohort tied to authenticated identities; never a guessable URL parameter or client header | adapt (deviation) | The Preview Token is an HMAC secret sent as `X-Preview-Token` or `?preview=`, not a guessable value. Accepted for a personal factory; the token must stay out of logs. |
| Dedicated tester accounts, tagged synthetic data, declared side effects, cleanup | adopt, done | `tester.md`: `factory-test-` tagged records, no real side effects, bounded requests, delete what it created, report what it could not. Dedicated tester accounts are not needed while the Preview Token is the only access path. |
| Test the kill switch and the flag-off state | adapt, partly done | The tester confirms a flagged feature is dark without the token. It holds no GrowthBook admin key, so it cannot flip the kill switch; instead the Orchestrator's watchdog reads back that its own disable call took effect (not yet exercised against real GrowthBook). |
| Gate membership: no incomplete change reachable through an ungated path | adopt, done | Reviewer rubric: routes, UI, middleware, background jobs, scheduled tasks, exports and notifications. |
| Expand/contract migrations; a flag cannot undo writes | adopt, done | `STANDARDS-CODING.md` (Data and migrations) and a blocking reviewer rubric item, with a smoke fixture. |
| Stop conditions and a named person who can disable | adapt, done | The watchdog turns the flags a run released off on a health or error regression and opens a needs-human Issue; the release step never re-enables them. Unverified against real GrowthBook. |
| Staged rollout: tester, then limited cohort, then progressive ramp | defer | Release is all-at-once today. Low traffic makes staged signals noisy; revisit with real users. |
| Remove the gate after full release and an observation period | adapt | Owner-requested only (Glossary: Retire); flag debt proposals go to the digest. Ticket: flag debt. |
| Human review for high-impact changes | adapt (deviation) | A clean AI review releases without a human; accepted while the factory is personal-scale. Prompt, standards and orchestrator changes to the Factory itself still get a human merge. |

## Verification

| Recommendation | Status | Notes / where |
|---|---|---|
| Deterministic checks first (tests, types, build, migration validation) | done | Test Gate and image build. Gaps: no dependency or secret scanning (ticket: maintenance and security gates). |
| Acceptance tests tied to issue criteria, including negative cases | adopt, partly done | The coder prompt requires real assertions plus an invalid or boundary case. The numbered `AC-n` criteria still depend on Intake triage (open ticket). |
| Review agent-written tests; presence is not evidence | adopt, done | Blocking reviewer rubric item for a test that cannot fail; `vacuous-test` smoke fixture (4/4 and 2/2 caught). |
| Independent reviewer distinct from the implementer | adapt | A separate Agent, but currently the same model as the coder (known deviation, `ARCHITECTURE.md`). |
| LLM findings are advisory, deterministic checks are not | done | The Orchestrator derives verdicts from findings and never trusts the model's own verdict. |
| Verification states: passed / failed / blocked / not run, plus limitations | adopt, done | `derive_test`, `verification_record`, the Summary and the Report. |
| Verification record per run | adapt | Folded into the existing Build Run Report rather than a new artifact. |
| Never claim a check passed unless observed | done | In the coder prompt and the Orchestrator's own derivation. |
| OpenHands Critic | defer | Advisory and product-dependent; replaced by an Orchestrator-written criteria scoreboard. |
| OpenHands `code-review` and `qa-changes` extensions | defer | PR-oriented, and we already have reviewer and tester roles. Re-check upstream setup and licensing before any adoption. |
| Playwright for UI journeys | defer | Add to the tester only for Managed Apps with a UI worth testing, after the current tester's detection rate is measured. |
| axe-core accessibility checks | defer | With Playwright. |
| Schemathesis | defer | Needs an OpenAPI schema; offline or against a local fixture, never production. |
| RESTler | reject (for now) | Needs an isolated disposable target; not a production tool. |
| Compare models on a fixed suite with an independent verifier | adopt | Ticket: whole-run benchmark and model-upgrade protocol. |

## Completion

| Recommendation | Status | Notes / where |
|---|---|---|
| Done only when criteria met, verification observed, reviewed and integrated | adapt, partly done | "Done" is every check `passed` with evidence, tracked by a scoreboard the Orchestrator writes each round (built); per-criterion `AC-n` tracking waits on Intake triage. |
| Do not call work complete because all agents returned | done | The release step and Summary report outcomes, not activity. |
| Status updates: completed outcomes separate from work in progress | adapt | The Build Run Summary and a morning digest. |

## Not in the advice but decided alongside it

Pre-mortem and gap decisions, and the larger plan, are in [.wayfinder/orchestrator-hardening/](../../.wayfinder/orchestrator-hardening/map.md).
