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
A worker process, backed by an LLM, spawned by the Orchestrator to carry out one role's unit of work (coding, reviewing, testing, or diagnosing a failed pipeline) within a Build Run.
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
The act of submitting an Intake Spec to the Orchestrator, proposing a new Managed App.
_Avoid_: submission, request

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
Enabling a feature's flag so it is available to all users.
_Avoid_: publish, go live

**Retire**:
Deleting a feature's flag and its code path after the feature is permanently on. Only done on the owner's explicit request.
_Avoid_: remove, clean up

**Preview Token**:
A secret that lets its holder see features still hidden behind a flag, while everyone else sees them dark.
_Avoid_: backdoor, bypass key
