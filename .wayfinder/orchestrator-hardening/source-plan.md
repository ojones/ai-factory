# NEXT ACTION (approved scope): chart a Wayfinder map for the "most likely to bite" gaps

The skill `/mattpocock-skills:wayfinder` is user-invoked only (`disable-model-invocation: true`), so I cannot call it. The repo already has a precedent in `.wayfinder/coder-speed/` (local-markdown tracker: `map.md` + `tickets/NN-*.md`, front matter `title/type/status/assignee/blocked_by`). I will create the map by hand in that exact format. Nothing is resolved or built in this step, and nothing is committed.

Create `.wayfinder/orchestrator-hardening/`:
- `map.md` (label `wayfinder:map`)
  - **Destination:** the Orchestrator is safe to run unattended across many Managed Apps. The eight gaps below are each decided, and the adopted changes are made in the repo.
  - **Notes:** execution override (as in coder-speed: a ticket may carry out its adopted change); local-markdown tracker; one ticket per session; consult `source-plan.md`; related files (`ARCHITECTURE.md`, `agents/profiles.yml`, `orchestrator/build_run.py`, `orchestrator/postmortem.py`, `.github/workflows/*`).
  - **Decisions so far:** the six decisions already made in this plan (update requests as ai-factory issues; one Build Run per change set; model-drift docs fix; Factory PRs auto-merge only mechanical changes; watchdog auto-disables; learn on first occurrence), each as a one-line gist.
  - **Not yet specified (fog):** the plan's larger pillars (gate record and scoreboard, learning loop v2 and Factory Run, assurance and dashboard, multi-app parallelism, planner), plus the "worth a line each" items (prompt injection from content, app growth, data and backups, code rollback, payoff metric, owner ergonomics).
  - **Out of scope:** staged rollout and UI/API tooling (Playwright, axe, Schemathesis, RESTler), until a measured gap exists.
- `source-plan.md`: a copy of this plan, so the context survives outside `~/.claude/plans`.
- `sources/`: copies of the three advice docs (`MANAGER.md`, `openhands-planning-guide.md`, `verification-tools-for-coding-agents.md`), unchanged.
- `tickets/` (all open, unassigned):
  1. `01-global-pause-and-circuit-breaker.md` (grilling): factory-wide stop switch, auto-trip rules, vacation mode.
  2. `02-queued-runs-dropped.md` (task): `queue: max` on the concurrency groups; auditor flags an Intake that never produced a run.
  3. `03-app-maintenance-and-security-gates.md` (grilling): scheduled maintenance Intakes, `npm audit` and secret scanning in the Test Gate, idle-app retirement.
  4. `04-production-feedback-loop.md` (grilling): turn recurring runtime errors and escaped defects into bug Intakes and lessons.
  5. `05-flag-debt.md` (grilling): digest proposals to retire old released flags, still owner-approved.
  6. `06-intake-triage-and-criteria.md` (grilling): feasibility triage, owner-confirmed criteria echo, golden Intakes; note that app repos and `INTAKE.md` are public.
  7. `07-tester-seeded-bug-fixtures.md` (task): tester fixtures that must fail, and whether mutation testing is worth it.
  8. `08-whole-run-benchmark-and-model-upgrade.md` (research), blocked by 7: a fixed Intake suite, a model-upgrade protocol, and a fallback model or provider.

Verification: the files match the `coder-speed` format; `blocked_by` names real filenames; each ticket's Question is sized to one session; `git status` shows only the new `.wayfinder/orchestrator-hardening/` folder. I will not commit unless asked.

---

# Background plan (source for the map)

# Plan: Fold the OpenHands-derived advice into the Orchestrator (v3: pre-mortem + learning loop)

## Context

Three advisory docs (`MANAGER.md`, `openhands-planning-guide.md`, `verification-tools-for-coding-agents.md`, in `~/Documents/Codex/2026-10-10/.../outputs/`) describe how to plan and verify coding-agent work. They assume one app and one manager. This Orchestrator builds and updates **many Managed Apps in parallel**, driven by GitHub issues, with the **change-set gate (a default-off feature flag) as the core of its test-in-production strategy**, and must run **unattended overnight**. It should also **learn from its own failures** through GitHub issues.

The advice fits as follows: adopt it for the gate record, verification states, acceptance criteria and test-quality review; adapt the planner ("ask the user" becomes a needs-human issue); defer the PR-oriented OpenHands extensions; use heavy tools (Playwright, axe, Schemathesis, RESTler) only against a measured gap. I have not re-verified the advice's URLs or benchmark numbers.

## Decisions made
1. Change requests for existing apps are ai-factory issues labelled `intake` + `app:<slug>`; the title stays the bare app name (`stage.sh` derives the repo and Fly names from it). State and outcomes stay in the Managed App repo; a registry issue in ai-factory gives the cross-app view.
2. A multi-change-set Intake runs as one Build Run per change set (small queue), each with its own gate and release. The 6-hour Actions job limit rules out one run for all.
3. Model drift: update ARCHITECTURE.md to match `agents/profiles.yml` (DeepSeek-V4.1-Flash for coder and reviewer) and record the shared-model risk against the "different lab" principle.
4. **Factory PRs:** lint, formatter and Starter Template-default changes auto-merge when every required check passes. Prompt, standards and orchestrator changes need a human merge.
5. **Post-release watchdog:** the Orchestrator turns a flag off automatically on a health or error regression, opens a needs-human issue and records a lesson. The release step never re-enables it.
6. **Learning threshold:** act on the first occurrence (today's behaviour). Because this raises the risk of overfitting to a one-off, the guardrails in Pillar D (lesson fixtures, required checks, recurrence tracking after merge, revert on "fix ineffective") are mandatory, not optional, and auto-merge is limited to purely mechanical changes.

## Pre-mortem: "it's a year from now and this failed. Why?"

Ordered by likelihood × damage. Each row names the evidence in the repo today and the mitigation.

| # | How it failed | Evidence today | Mitigation |
|---|---|---|---|
| 1 | **A wrong-but-green change shipped to every user.** Coder and reviewer are the same model; the tester is a 12-call `curl` pass; release is automatic and terminal. | `profiles.yml` (both DeepSeek-V4.1-Flash); `tester.md`; `release_gate` | Record the shared-model risk (decision 3) and revisit; acceptance-criteria scoreboard; test-quality rubric; tester evidence and kill-switch check. |
| 2 | **Test-in-prod with no prod signal.** After release nothing watches the app, so a bad release is found by users. | Release is the last step in `build_run.py` | **Post-release watchdog** (decision 5): a deterministic step watches health and error logs for N minutes and flips the flag off on regression. Redeploying the previous SHA stays the fallback. |
| 3 | **A data change a flag can't undo.** A migration applies on deploy, for everyone, while the feature is "dark". | No migration standard in `STANDARDS-*` | Add expand/contract migration rules to the standards; reviewer rubric item: schema changes in a flagged update must be additive. |
| 4 | **Ungated paths.** First builds go live on deploy; bug fixes, refactors and dependency bumps are unflagged; the Test Gate is unit tests plus a boot smoke. The gate is the core strategy but covers only part of the traffic. | `STANDARDS-FEATURE-FLAGS.md` | State the exceptions deliberately. Default to flagging fixes too (a flag is cheap). The watchdog covers the rest. |
| 5 | **One compromised or broken shared thing takes everything down.** One GrowthBook + free-tier Mongo, one all-repos PAT, one Fly token; Agents run as the same OS user and could read the PAT from `/proc`. Parallel apps multiply the blast radius and the prompt-injection surface. | ARCHITECTURE.md "Known gap" | Run Agents as a separate OS user **before** lifting the one-app limit. Alert on GrowthBook outage. |
| 6 | **Spend runaway.** Per-run caps exist, but parallel apps × overnight × the post-mortem Agent (outside any cap) × retries. The DeepInfra account cap is the only ceiling. | `postmortem_timeout_minutes`; "outside the Build Run's cost cap" | A daily/global spend ledger in the Orchestrator with a hard stop; the post-mortem and Factory Run Agents get their own daily cap. |
| 7 | **The learning loop degrades the Factory.** Prompts accrete rules and get slower; the post-mortem Agent can edit the reviewer's own prompt; nothing evaluates its PRs; acting on the first occurrence overfits; the docs already drift from config. | `postmortem.py` `ALLOWED_PREFIXES` includes `agents/`, `STANDARDS*`, `ARCHITECTURE.md` | Pillar D: lesson fixtures, replay/smoke as required checks, fix-type ladder, prompt-size budget, post-merge recurrence tracking. |
| 8 | **Template drift.** Starter Template improvements never reach already-seeded apps, so 20 apps sit on 20 template versions. | Starter is seeded once by `git archive` | Stamp the template version in each app; generate "template sync" update Intakes from template diffs. |
| 9 | **Silent overnight failures.** Model IDs get retired, OpenHands changes its CLI or output, a provider rate-limits parallel runs, a token expires; the owner finds out days later or is buried in N reports. | Pinned model IDs; check whether `openhands` itself is pinned | Pin OpenHands; nightly canary smoke run that opens a learning issue on drift; one morning digest instead of per-run noise. |
| 10 | **Wrong app built confidently.** A free-text Intake is misread; the tester verifies against the same misreading. | `INTAKE.md` is one free-text field | Criteria extraction echoed back as a comment; the owner can correct it before a larger build. |
| 11 | **We built too much too soon.** Only one Managed App has been proven end to end (ARCHITECTURE.md says so); this plan adds a planner, registry, scoreboard and Factory Runs. A one-person system's maintenance outgrows its payoff. | Intake section, "once a single new Managed App has been proven" | Sequence by evidence (phasing below). Add a feature only when a learning issue asks for it. |
| 12 | **The owner is the bottleneck.** Needs-human issues, learning PRs, N repos of outcomes, and no one else to review. | n/a | Digest; caps on open learning PRs and needs-human items per app; auto-close stale items. |

## Pillars

### A. Many apps in parallel
- Per-app serialisation already exists (`build-run.yml`: `concurrency: build-run-${{ inputs.app_name }}`, no cancel). What blocks parallel apps is the global gate: `max_simultaneous_build_runs: 1` (`profiles.yml`; enforced in `build_run.py` ~L511, which waits 30 min), `stage.sh` L97, and the shared `app-staging` group in `app-staging.yml` and `teardown.yml`. Replace the global limit with a ceiling and keep the per-app group. **Queue gotcha:** with `cancel-in-progress: false`, GitHub keeps only one pending run per concurrency group and cancels an older pending one when a newer arrives, so a per-change-set queue (decision 2) would silently drop runs. Add `queue: max` to the group (GitHub changelog, 2026-05-07, up to 100 queued), and have the auditor flag any Intake that never produced a run.
- Identity: Intake issues get an `app:<slug>` label; titles stay as they are. Needs-human, budget-exhausted and "released" items stay in the Managed App repo. State: a pinned **App State issue** per app (change sets, gate/flag key and state, last SHA, last run and cost, requirements `REQ-n` with criteria). **Not a file on `main`**: an Orchestrator commit would break "only the coder reaches `main`", redeploy on every docs-only change, and race the release step. `INTAKE.md` stays the immutable original.
- A registry issue in ai-factory lists one row per app, linking each App State issue, and feeds the morning digest.

### B. The change-set gate as a recorded, central object
- Gate record per change set: flag key `<app>.feature.<slug>`, scope (issue/requirement IDs), state `dark → tester_verified → released → retired`, stop conditions, who can disable. Lives in `flags.json` plus the App State issue.
- One gate per change set; a first build needs none. Release stays a deterministic step and now also requires gate membership verified and no criterion `blocked` or `not_run`.
- Reviewer rubric: every new user-facing entry point is guarded server-side, and schema changes are additive. The tester exercises the flag-off state (ordinary caller can't reach it), the flag-on state (Preview Token), and the kill switch once per release.
- Post-release watchdog (decision 5) and tester safety rules: tagged synthetic data, declared side effects, bounded requests, cleanup, no fuzzing of production.
- Accepted deviations from the advice, recorded in `ADOPTION.md`: the Preview Token is a header/query secret (the advice says never use a client-controlled header); a clean AI review releases without human review; staged rollout is deferred.

### C. Overnight autonomy: a machine-checkable definition of "on track" and "done"
- Acceptance criteria `AC-1…` per change set, each tied to an executable check. Done means every criterion `passed` with observed evidence.
- A criteria **scoreboard** (`progress.json`), written by the Orchestrator each round (`passed | failed | blocked | not_run`, evidence, SHA). The next coder round reads it. It replaces the OpenHands Critic, which is advisory and product-dependent.
- Stuck detection: no scoreboard change for N rounds, or a repeating finding, ends the run with a needs-human issue rather than burning the budget. Runs resume from the scoreboard and App State issue rather than restarting.
- The morning Summary leads with the scoreboard, gate state and needs-human items; checks not run are listed as limitations.

### D. Self-healing and self-learning through GitHub issues
**What exists** (`orchestrator/postmortem.py`, `agents/prompts/postmortem.md`, `build-run.yml` L86): after a run, stuck outcomes and open minor findings become `factory-learning` issues in ai-factory, deduplicated by a fingerprint (outcome plus the first six meaningful words) with "Happened again" comments; minor findings also get a suggestion issue in the app repo; a post-mortem Agent edits a Factory checkout (prompts, Starter Template, orchestrator), and the Orchestrator validates paths, runs the unit tests and opens a PR for a human. It acts on the first occurrence. ARCHITECTURE.md and the GLOSSARY never mention it.

**What to change:**
1. **More signals**, each recorded as a structured lesson (category, fingerprint, app, run, evidence): runs that succeeded but needed ≥2 fix rounds or a pipeline retry; first-pass tester failures the coder later fixed; flaky diagnoses; budget over 70%; stage-time outliers; needs-human outcomes; watchdog auto-disables and owner rollbacks; issues labelled `escaped-defect` in an app repo; the nightly canary's drift findings.
2. **Act on the first occurrence** (decision 6), but track recurrence: a weekly consolidator clusters near-duplicate lessons (six-word fingerprints are brittle) and counts distinct runs and apps. Recurrence tells the human which lessons matter and drives the "fix ineffective" check below. It isn't a gate on acting.
3. **Factory Run**: a Build-Run-like workflow whose target is ai-factory itself, triggered when a lesson is recorded (or by a `ready-for-factory-run` label on an older one). It uses a `factory-coder` prompt and edits `templates/starter/` (lint and formatter config, `AGENTS.md`, test scripts), `agents/prompts/`, `STANDARDS*` and `orchestrator/`; never `.github/` or secrets (existing `DENIED_PREFIXES`). Output is a PR.
4. **Merge policy** (decision 4): auto-merge only when every changed path is lint/formatter config or a Starter Template default, the change is additive (adds or tightens a deterministic check, never loosens one), and all required checks pass. Everything else waits for a human.
5. **Fix-type ladder.** The Factory coder prefers, in order: a deterministic check (lint rule, type rule, test, template default) → a Starter Template default → a prompt instruction → an orchestrator change. Prompt prose is last because prompts bloat. This moves recurring style and quality findings from LLM review into mechanical gates, as the advice recommends, and fits `STANDARDS-CODING.md`'s "style is purely mechanical".
6. **Every lesson ships with a regression fixture.** A Factory PR must add a replay or smoke case (`agents/replay/cases.json`, `agents/smoke/fixtures`, or a unit test) or state why not. Required checks: `python -m unittest discover orchestrator`, reviewer smoke/replay (`reviewer-replay.yml`, `smoke-reviewer-model.yml`), and `npm ci && check && test` in `templates/starter`. A change to a reviewer or rubric prompt must show no loss on the reviewer fixtures.
7. **Close the loop.** After a lesson's PR merges, track whether the lesson recurs. If it does, reopen it as "fix ineffective" and mark the PR a revert candidate. A tightened lint rule that makes later runs fail (a rise in stuck runs after the merge) triggers the same review.
8. **Propagate to existing apps.** A merged Starter Template change generates a **template-sync** update Intake per app (`intake` + `app:<slug>`), running through the normal Build Run. Stamp each app with its template version.
9. **Guardrails.** Daily spend cap for the post-mortem and Factory agents; a cap on open learning PRs (for example 3); a prompt-size budget; changes to `STANDARDS*` or `ARCHITECTURE.md` are called out in the PR and never auto-merged. Scope note: the "no branches, no PRs" rule in `STANDARDS-CODING.md` applies to Managed Apps, not to Factory PRs; say so.
10. **Self-healing at runtime** (separate from learning): the nightly canary smoke run, pinned OpenHands, backoff retries for infra, and the watchdog.

### E. Assurance and monitoring: prove it behaves as designed, and see it across apps
Three layers, cheapest first. Nothing here needs a new always-on service at the start.
1. **Design invariants as executable tests.** Extract the "must" rules from ARCHITECTURE.md and STANDARDS-* into `docs/invariants.md`, each with an ID (for example INV-07: a coder commit touching a protected file is discarded; INV-12: release requires CI green + deploy healthy + tester pass + reviewer clean for the same SHA; INV-15: the Orchestrator derives the verdict, never the model; INV-21: no Agent environment holds the PAT, Fly token or GrowthBook admin key; INV-30: new flags are created off). Each ID maps to a test in `orchestrator/test_build_run.py` or a new `orchestrator/test_invariants.py`; a CI check fails if an invariant has no test. The 58 existing unit tests cover part of this; the registry shows what is not covered, and makes drift between docs and config (rounds 10 vs 4) fail CI.
2. **End-to-end with a stub LLM.** The provider `base_url` is already config (`profiles.yml`). Add a tiny local OpenAI-compatible stub that replays recorded responses, and run a full Build Run against a permanent **canary app** nightly and on every orchestrator PR: free, deterministic, and it catches orchestration bugs (ordering, handoffs, limits) separately from model quality (the existing `agents/smoke` and `agents/replay` suites). Add fault-injection cases: failing CI, a hung Agent, budget breach, a seeded reviewer bug, a coder touching a protected file, a watchdog regression.
3. **Audit real runs.** A post-run **auditor** (deterministic, reads the Build Run Report that already lands in `artifacts/build-run-report.json`) checks the invariants against what actually happened: stage order, cost ≤ cap + one-call overshoot, release only on a four-way pass, no flag re-enabled. A violation becomes a lesson issue (Pillar D) and a morning-digest line.

**Monitoring UI: build a thin data layer, adopt a generic viewer, defer LLM-trace tooling.**
- Every Build Run Report and lesson is appended to a durable store (a SQLite file or a `factory-data` repo of JSON) by an Actions step. A scheduled job renders a **static dashboard** to GitHub Pages: per-app status and gate state, runs per day, rounds per run, first-pass rate, cost per app and per day against the ledger, human-intervention rate, escaped defects, watchdog disables, lesson recurrence and "fix ineffective" counts, template-version spread. It is the digest's web form.
- When the app inventory outgrows static pages (roughly 5+ apps or ~50 runs/month, to be revisited), point Metabase or Grafana at the same store. Both are open-source and self-hostable, but each is a new always-on service, which cuts against the "ephemeral, pay only while a run is active" principle.
- LLM-trace tools (Langfuse, Arize Phoenix, Laminar) answer "what did the model do inside this run", not "is the factory on track". The OpenHands SDK documents built-in OpenTelemetry tracing, but the Orchestrator drives the `openhands --headless` CLI, so whether it honors the OTLP environment variables is **unverified** and needs a spike. We already keep each invocation's JSONL event stream and token/peak-context usage. Revisit traces when debugging in-run model behaviour becomes the bottleneck. Langfuse is MIT but needs Postgres, ClickHouse, Redis and blob storage; Phoenix is a single process but under the Elastic License 2.0 (not OSI-approved).
- Define the success metrics now, before building anything, so the plan itself can be judged (there is no baseline yet).

## Phasing (ordered by the pre-mortem, each independently shippable)
1. **Reconcile docs.** Add `docs/advice/` with the three docs, a README (sources, "advisory; ARCHITECTURE.md wins") and `ADOPTION.md` (every recommendation marked done / adopt / adapt / defer / reject). Fix the drifts: review rounds (10 vs 4), models, per-Agent cost wording, GLOSSARY gaps (postmortem role, Test Gate, flag manifest, terminology mapping), "every update flagged" vs "unflagged fixes", `INTAKE.md` as the spec for updates. Document the existing learning loop in ARCHITECTURE.md.
2. **Gate and verification core** (Pillars B, C) with the post-release watchdog and migration standard. Files: `agents/prompts/*`, `agents/README.md`, `derive_test` / `derive_review` / `release_gate` / `render_summary` in `orchestrator/build_run.py`, `orchestrator/test_build_run.py`, a vacuous-test fixture in `agents/smoke/`.
2b. **Assurance** (Pillar E, layer 1 and 3 first): invariants registry and tests, the run auditor, the data store, the static dashboard; then the stub-LLM canary run; then the OpenTelemetry spike. Cheap, and it makes every later phase checkable.
3. **Learning loop v2** (Pillar D), which reuses `postmortem.py`: more signals, fix-type ladder, lesson fixtures and required checks, then the Factory Run workflow with the merge policy, then template-sync.
4. **Hardening prerequisites for parallel:** separate OS user for Agents, global spend ledger, pinned versions, canary run, digest.
5. **Multi-app parallelism** (Pillar A): lift the global limit, labels, App State issue, registry.
6. **Planner stage:** a read-only `planner` role that turns a larger Intake into ordered change sets with criteria, plus a deterministic plan validator; failure ends in a needs-human issue. Depends on 2, 3 and 5.
7. **Deferred:** staged rollout, UI evidence tooling (Playwright/axe) when an app has a UI worth testing, Schemathesis once apps expose an OpenAPI schema (offline only).

## Critical files
- New: `docs/advice/*`; `agents/prompts/factory-coder.md`, `agents/prompts/planner.md`; a Factory Run workflow beside `.github/workflows/build-run.yml`; the watchdog and plan validator in `orchestrator/`.
- Edited: `ARCHITECTURE.md`, `GLOSSARY.md`, `STANDARDS-FEATURE-FLAGS.md`, `STANDARDS-CODING.md`, `agents/profiles.yml`, `agents/README.md`, `agents/prompts/{coder,reviewer*,tester,postmortem}.md`, `orchestrator/{build_run,postmortem}.py` and their tests, `infra/app-staging/stage.sh`, `.github/workflows/{app-staging,teardown,build-run}.yml`, the Intake form.
- Reuse: `release_gate`, `derive_*`, the per-agent JWT budget, `collect_facts` / `record_issue` / `record_minors` / `open_pr` in `postmortem.py`, `allowed_path`, the smoke and replay suites.

## Verification
- Unit tests for the new `derive_*` / `release_gate` states, the stuck detector, the watchdog decision, lesson clustering and the auto-merge path check.
- Rerun `agents/smoke/run.py` and `agents/replay/` after every prompt change.
- Learning loop: replay a recorded stuck run and confirm a lesson, a Factory PR with a fixture, and passing required checks; seed a lint lesson and confirm it auto-merges only when additive and green; seed a prompt-only lesson and confirm it waits for a human; seed a recurrence after merge and confirm "fix ineffective".
- Watchdog: deploy a deliberately failing flagged change to a test app and confirm the flag is turned off without a human.
- Multi-app: start two Intakes for different apps at once and confirm both run with separate flag keys and labels; start two Build Runs for one app and confirm the second queues.
- Overnight: one real Build Run with an unmeetable criterion; confirm stuck detection ends it with a needs-human issue and a scoreboard.
- Assurance: delete the test for one invariant and confirm CI fails; break the release rule in a branch and confirm the invariant test and the canary run both fail; feed the auditor a doctored report and confirm it files a lesson.
- Confirm the added steps stay inside the default $2 cap.
