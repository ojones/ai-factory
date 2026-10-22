# ai-factory

A personal, cost-conscious system that runs long, unattended agentic coding sessions to build and deploy separate software applications, following standards authored in this repo.

## Language

**Factory**:
This repo and everything it defines: the Standards, the Orchestrator, and the record of what it has built. Not itself a running process.
_Avoid_: the system, the platform

**Orchestrator**:
The ephemeral compute that runs a Build Run — scheduling its stages, dispatching work to Agents, and enforcing the Standards — and exists only while that run is active.
_Avoid_: the factory (when the runtime process specifically is meant), the runner

**Agent**:
A worker process, backed by an LLM, spawned by the Orchestrator to carry out one role's unit of work (coding, reviewing, testing, or diagnosing a failed pipeline) within a Build Run, or by the retrospective step after every Build Run (reading what the run found and how it ended).
_Avoid_: bot, worker

**Standards**:
The authored conventions — coding style, repo layout, container, and deployment rules — that Agents must follow when producing a Managed App. Kept in the Starter Template's `AGENTS.md` (what a coder follows) and ARCHITECTURE.md (why).
_Avoid_: rules, guidelines

**Managed App**:
A backend+frontend software product produced by the Factory, containerized and deployed via GitHub. Distinct from the Factory itself.
_Avoid_: product, project, built application (former term, renamed)

**Build Run**:
A single unattended execution of the Orchestrator, from kickoff to completion, working toward producing or updating one Managed App.
_Avoid_: job, session

**Intake**:
A request to the Orchestrator, filed as a GitHub issue on this repo: a New App Intake or an Update App Intake. It is the parent of the child tickets planning files for it.
_Avoid_: submission, request

**New App Intake**:
A GitHub issue (label `new-app-intake`) proposing a new Managed App, carrying its Intake Spec. Applying the label starts planning; the first child ticket of its plan stages the app. (Today `ready-for-staging` starts App Staging with no plan; the new start is in the Wayfinder map `.wayfinder/intake-planning-redesign/`.)
_Avoid_: first intake, Managed App Intake

**Update App Intake**:
A GitHub issue (label `update-app-intake`) asking the Factory to change a Managed App it already built. The owner files it with the form; template sync, maintenance, flag retirement and the Try Fix Agent's bug tickets file it with the PAT. Applying the label starts planning. (Today `proceed-with-change` starts a Build Run that plans first.)
_Avoid_: Update Intake (former term), ticket, change ticket

**Planning**:
The process, separate from any Build Run, that reads an Intake (a New App Intake from its spec, an Update App Intake also from the app's code) and files child tickets. It can end by refusing the request, stopping for a person, or planning. Run by the Planner Agent and the deterministic gate in `planning/validate_plan.py`.
_Avoid_: triage (that is the refusal checks inside planning)

**Child ticket**:
A GitHub sub-issue of an Intake, filed by planning: one change set as a complete set of coding instructions, sized so one feature flag can roll it back, with a `factory-plan` marker. A Build Run is started for exactly one child. Its number is the number in its flag's slug, `issue-<n>`.
_Avoid_: sub-task, change ticket, child Update App Intake (former term)

**Staging child**:
The first child ticket of a New App Intake (`kind: staging`): stages the app and verifies the infrastructure and connections before any business logic, with no flag.
_Avoid_: setup ticket

**Bug Intake**:
An `update-app-intake` labelled `bug`, written by the Try Fix Agent from the bug template and planned like any Intake. For a child that failed it carries `fix_for` (the failed child): its plan is exactly one child, and the failed child waits for it. For a story that is already released it is a regression: it carries no marker and nothing waits for it. (Built, ticket 15d. The one child it plans is called a **fix child**; it is filed under the bug Intake, not under the failed child's parent.)
_Avoid_: retry, hotfix

**Failure event**:
One thing that went wrong or looks wrong, with its source, severity (`failure` or `warning`), app, story, fingerprint and evidence. The Retrospective gives every event a verdict, `fix` or `record`. (Target, ticket 15b.)
_Avoid_: alert, incident

**Try Fix Agent**:
The Agent with one job: write a good bug ticket from the bug template for each `fix` verdict (how it was found, root cause, what it takes to resolve, checkable requirements). It does not decide the cause or target and does not plan. One model call with its own capped credential; the Orchestrator validates the answer and writes the ticket itself if it is unusable. (Built, ticket 15c; filing the ticket is ticket 15d.)
_Avoid_: fixer

**Domain**:
One named part of the Factory's flow that owns a set of steps in the flow spec, with its own code, tests and documentation, so it can be changed or extended without touching the others. The domains are Request, Planning, Staging, Build Run, Flag Lifecycle, Retrospective (record and advance included), Try Fix and Bugs, plus Maintenance and Monitoring for work outside the request flow.
_Avoid_: group (former term in the flow spec), module, package, service

**Shared**:
The one folder of code that two or more domains use (the GitHub client, the child-ticket model, the Agent runner, the list of Build Run endings, config). It imports no domain.
_Avoid_: tools, kernel, utils

**Flow spec**:
`docs/flow-spec.md`: the numbered diagram and step index of how a request becomes a running, recorded change. Steps are cited by ID, `STEP 4.9`; IDs are never renumbered.
_Avoid_: the diagram, the workflow doc

**Intake Spec**:
The description of a Managed App to be built — scope and constraints — submitted via Intake, before its repo or any infrastructure exists.
_Avoid_: idea, ticket, project

**App Staging**:
The one-time setup of a new Managed App's baseline — repo, seeded Starter Template code, and secrets (including its GrowthBook SDK key) — that happens after an Intake Spec is accepted and before its first Build Run.
_Avoid_: provisioning (as a Factory-level phase name; the word still applies loosely to individual scripts/steps within App Staging), bootstrapping, onboarding

**Starter Template**:
The fixed repo scaffold — directory structure, CI config, boilerplate — that App Staging seeds every new Managed App from.
_Avoid_: scaffold, boilerplate

**Build Run Summary**:
The human-readable record (status, what changed, test results, cost spent, deploy outcome) a Build Run leaves on its GitHub Actions run page.
_Avoid_: the log, the report

**Build Run Report**:
The machine-readable counterpart to the Build Run Summary — a structured artifact carrying the same fields, for future tooling to consume.
_Avoid_: the summary

**Deploy**:
Making a Managed App's new code live on its host. Deployed code may still be hidden behind a feature flag.
_Avoid_: publish, ship (as a synonym for Release)

**Release**:
Enabling the flag that gates an update so the change is available to all users.
_Avoid_: publish, go live

**Retire**:
Deleting a released flag's check and its line in `flags.json` once the change is proven and a later release has come after it, keeping the behaviour on. Automatic, under the owner's standing approval in ARCHITECTURE.md (Release and retirement), inside an Update App Intake's Build Run that is already coming in for the same app (never a run of its own); the flag is then archived in GrowthBook.
_Avoid_: remove, clean up

**Test Gate**:
The hard gate in a Managed App's deployment pipeline: install, type-check and unit tests plus one boot smoke test. Nothing deploys unless it and the image build both pass for the commit.
_Avoid_: CI (when this specific gate is meant)

**Flag slug**:
The `<slug>` part of a flag's GrowthBook key `<app>.feature.<slug>`. `issue-<n>`, `<n>` the number of the story it belongs to (an issue that runs again keeps its flag). The Orchestrator names it; older flags keep the slug their planner chose.
_Avoid_: flag name, flag id

**Flag manifest**:
`flags.json` at a Managed App's root: the flags a change introduced, recorded in the same commit. The release step reads it to know what to create and enable.

**Change-set gate**:
The name used in outside advice for what the Factory implements as the flag around one update: a default-off, server-enforced flag that keeps a not-yet-trusted change dark for ordinary users while the tester exercises it with the Preview Token. One update has one gate; a first build has none. In this repo say "flag" or "the update's flag"; "change-set gate" appears only when citing the advice (see the archived advice documents (git tag `archive/pre-purge-2026-10-21`)).
_Avoid_: feature flag (as a name for the gate itself; it is the underlying mechanism)

**Lesson**:
A `factory-learning` issue in ai-factory recording something a Build Run taught the Factory (a stuck run, a recurring minor finding), from which the retrospective Agent may propose a change to prompts, the Starter Template or the Orchestrator as a PR.
_Avoid_: retrospective (that is the step and Agent that read every run and may file or act on these)

**Retrospective**:
The step that runs after every Build Run, whether it released or not. It records what the run found (blocking findings, minor findings and the `improvements` the reviewer and tester suggest), files them as issues in the Managed App's repo or ai-factory, may propose a Factory fix as a PR, and posts a short summary on the issue that started the run.
_Avoid_: post-mortem (it is not only for failures)

**Dark feature**:
A change whose flag has not been released. One that fails its checks stays dark and is fixed forward (by a fix child, then its own child runs again); it is tracked by its story issue (`flag:<slug>`, plus `dark-broken` once the run that built it could not get it through), not by `flags.json`. It is removed only after its fix attempts are used up and a person approves (`approve-retire`).
_Avoid_: dead flag

**Fix request**:
The issue a Build Run that ended badly leaves behind: what happened, what the Orchestrator already did (a deploy rollback, for a regression), an automated analysis, and numbered requirements for what must be true once it is fixed. It is routed to the Factory (a PR for a person to merge), to the app as a fix child (today: the same issue started again), or kept as information (`needs-human`).
_Avoid_: bug report, incident

**Scoreboard**:
The Orchestrator's per-round record of every check's state (`passed`, `failed`, `blocked`, `not_run`) and the blocking findings still open, written to the Build Run Report and `artifacts/progress.json`. It, not an Agent's say-so, is how the run knows whether it is making progress; a run that leaves the same items open for `stuck_rounds` rounds stops.

**Watchdog**:
The Orchestrator step after a release (STEP 5.8) that watches the app's health and error logs for a few minutes and switches off the flags the run released if they regress.

**Preview Token**:
A secret that lets its holder see features still hidden behind a flag, while everyone else sees them dark.
_Avoid_: backdoor, bypass key
