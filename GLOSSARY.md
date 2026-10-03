# ai-factory

A personal, cost-conscious system that runs long, unattended agentic coding sessions to build and deploy separate software applications, following standards authored in this repo.

## Language

**Factory**:
This repo and everything it defines: the Standards, the Orchestrator, and the record of what it has built. Not itself a running process.
_Avoid_: the system, the platform

**Orchestrator**:
The long-running service that schedules and supervises Build Runs, dispatching work to Agents and enforcing the Standards.
_Avoid_: the factory (when the runtime process specifically is meant), the runner

**Agent**:
A worker process, backed by an LLM, spawned by the Orchestrator to carry out one unit of coding work within a Build Run.
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
The one-time setup of a new Managed App's infrastructure — repo, secrets, Fly app, GrowthBook SDK key — that happens after an Intake Spec is accepted and before its first Build Run.
_Avoid_: provisioning (as a Factory-level phase name; the word still applies loosely to individual scripts/steps within App Staging), bootstrapping, onboarding

**Starter Template**:
The fixed repo scaffold — directory structure, CI config, boilerplate — that the Orchestrator seeds every new Managed App from at the start of a Build Run.
_Avoid_: scaffold, boilerplate

**Build Run Summary**:
The human-readable record (status, what changed, test results, cost spent, deploy outcome) a Build Run leaves on its GitHub Actions run page.
_Avoid_: the log, the report

**Build Run Report**:
The machine-readable counterpart to the Build Run Summary — a structured artifact carrying the same fields, for future tooling to consume.
_Avoid_: the summary
