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
A worker process, backed by an LLM, spawned by the Orchestrator to carry out one role's unit of work (coding, reviewing, testing, or diagnosing a failed pipeline) within a Build Run, or by the post-mortem step afterwards (analysing a run that did not end clean).
_Avoid_: bot, worker

**Standards**:
The authored conventions — coding style, repo layout, container, and deployment rules — that Agents must follow when producing a Managed App.
_Avoid_: rules, guidelines

**Managed App**:
A backend+frontend software product produced by the Factory, containerized and deployed via GitHub. Distinct from the Factory itself.
_Avoid_: product, project, built application (former term, renamed)

**Build Run**:
A single unattended execution of the Orchestrator, from kickoff to completion, working toward producing or updating one Managed App.
_Avoid_: job, session

**Intake**:
The act of submitting an Intake Spec to the Orchestrator, proposing a new Managed App. A change request for an existing Managed App is submitted as an Update Intake.
_Avoid_: submission, request

**Update Intake**:
A GitHub issue (label `update-intake`) asking the Factory to change a Managed App it already built. Adding the label `proceed-with-change` starts a Build Run for it at once, with no App Staging. A request the planner splits into several change sets becomes one child Update Intake per change set, run in order.
_Avoid_: ticket, change ticket

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
Deleting a released flag and its code path after the change is permanently on. Only done on the owner's explicit request.
_Avoid_: remove, clean up

**Test Gate**:
The hard gate in a Managed App's deployment pipeline: install, type-check and unit tests plus one boot smoke test. Nothing deploys unless it and the image build both pass for the commit.
_Avoid_: CI (when this specific gate is meant)

**Flag manifest**:
`flags.json` at a Managed App's root: the flags a change introduced, recorded in the same commit. The release step reads it to know what to create and enable.

**Change-set gate**:
The advice documents' name for what the Factory implements as the flag around one update: a default-off, server-enforced flag that keeps a not-yet-trusted change dark for ordinary users while the tester exercises it with the Preview Token. One update has one gate; a first build has none. In this repo say "flag" or "the update's flag"; "change-set gate" appears only when citing the advice (see [docs/advice/](docs/advice/README.md)).
_Avoid_: feature flag (as a name for the gate itself; it is the underlying mechanism)

**Lesson**:
A `factory-learning` issue in ai-factory recording something a Build Run taught the Factory (a stuck run, a recurring minor finding), from which the post-mortem Agent may propose a change to prompts, the Starter Template or the Orchestrator as a PR.
_Avoid_: post-mortem (that is the step and Agent that analyse it)

**Scoreboard**:
The Orchestrator's per-round record of every check's state (`passed`, `failed`, `blocked`, `not_run`) and the blocking findings still open, written to the Build Run Report and `artifacts/progress.json`. It, not an Agent's say-so, is how the run knows whether it is making progress; a run that leaves the same items open for `stuck_rounds` rounds stops.

**Watchdog**:
The Orchestrator step after a release that watches the app's health and error logs for a few minutes and switches off the flags the run released if they regress.

**Preview Token**:
A secret that lets its holder see features still hidden behind a flag, while everyone else sees them dark.
_Avoid_: backdoor, bypass key
