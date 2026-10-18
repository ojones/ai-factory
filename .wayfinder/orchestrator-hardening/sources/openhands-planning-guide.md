# Planning Coding Work for an OpenHands Managed App Workflow

## Purpose

This guide describes how to turn a proposed application and its requirements into a reviewable, dependency-aware plan that coding agents can execute. It is intended to be shared with a Claude coding session or used as the planning standard for an OpenHands-managed workflow.

The central rule is: **separate understanding the request, planning the work, implementing it, and verifying it.** The planner owns requirements coverage, decomposition, dependencies, and evidence of completion. A coding agent receives one bounded work item at a time. A reviewer checks the result against the original requirements.

### Workflow-specific operating model

This workflow uses **trunk-only development on `main`**: there are no feature branches. Changes are integrated into `main` in small increments. Production is the only deployed runtime environment available for feature testing. A server-controlled feature flag is used as a **change-set release gate**: it keeps an incoming, not-yet-trusted issue/change set dark from ordinary callers while authorized testers validate it in production. A gate may cover one issue/change set or several related issues that must be released together; there is no requirement for one flag per feature, and trusted changes do not automatically need a new flag. Once the gated change set has sufficient evidence, enable it for callers in a controlled rollout. Production testing is a deliberate release process with safeguards; it is not an invitation to run unbounded experiments on customer data.

Use **GitHub issue** for the work-tracking item and **change set** for the bounded code change implemented to complete that issue. The planner decomposes requirements into GitHub issues; each issue is one change set, with its own scope, dependencies, acceptance criteria, implementation, and verification record. Use the term **change-set gate** (or **release gate**) for the optional rollout control. Reserve “feature flag” for the underlying technical mechanism. One issue/change set may contain several related implementation details or user-facing capabilities; a gate is not necessarily one flag per feature. If multiple issues must be released together, record that intentional grouping and shared gate explicitly.

## Evidence and practical findings

OpenHands' articles point to a consistent set of practices:

1. **Make agent work small enough to review.** OpenHands describes coding agents as strongest on small, atomic tasks, ideally tasks that take a small number of attempts and yield a contribution a person can validate. It cautions that directory-by-directory decomposition is suitable for some incremental transformations but not all larger tasks. Derive GitHub issue/change-set boundaries from behavior and dependencies, not arbitrary file counts. ([Automating Massive Refactors with Parallel Agents](https://hub.openhands.dev/blog/automating-massive-refactors-with-parallel-agents))
2. **Represent dependencies explicitly.** The CAID system described in OpenHands' asynchronous-agent article has a manager build a dependency graph, assign structured subtasks to isolated worktrees, integrate completed changes, run tests, and adapt the plan. Its benchmark improvements (14.3 percentage points on Commit0 and 26.7 on PaperBench, as reported in the article) are evidence for those evaluated settings, not a guarantee for every application. ([Effective Strategies for Asynchronous Software Engineering Agents](https://hub.openhands.dev/blog/asynchronous-software-engineering-agents))
3. **Treat verification as part of the work.** OpenHands describes agent-level checks, repository-level review, and functional QA as different verification layers. Issue acceptance criteria should say what evidence demonstrates behavior and what regression checks apply. ([The Verification Stack](https://www.openhands.dev/blog/20260506-the-verification-stack); [Learning to Verify AI-Generated Code](https://www.openhands.dev/blog/20260305-learning-to-verify-ai-generated-code))
4. **Parallelism needs isolation and integration.** Separate workspaces prevent concurrent edits from overwriting each other, but do not remove interface or merge conflicts. Parallelize only work that is independent given agreed contracts; integrate and test continuously. ([Effective Strategies for Asynchronous Software Engineering Agents](https://hub.openhands.dev/blog/asynchronous-software-engineering-agents))
5. **A coding agent needs a clear task and repository context.** A GitHub issue should state the outcome and constraints; repository instructions should describe conventions and verification, while the issue describes the specific change set. Coding agents plan, act, observe results, and iterate, so provide useful access to repository tools and checks. ([What Are Coding Agents? A Developer's Guide to Agentic Coding](https://hub.openhands.dev/blog/what-are-coding-agents))
6. **Separate deployment from user release.** Feature flags can keep code deployed but hidden from normal callers, support tester-only access, and provide a quick disable path. Dark launching can reveal production load and operational effects, while staged canaries limit exposure and compare signals. ([Martin Fowler, Dark Launching](https://martinfowler.com/bliki/DarkLaunching.html); [Feature Toggles](https://martinfowler.com/articles/feature-toggles.html); [Google SRE, Canarying Releases](https://sre.google/workbook/canarying-releases/))

These are engineering practices and reported research outcomes, not a universal formula for issue size or team speed.

## The workflow: requirements to verified delivery

### 1. Analyze requirements

Rewrite the request as observable outcomes. Preserve the user's language where it expresses product intent. Separate:

- User-visible behaviors and user journeys.
- Data, privacy, security, accessibility, performance, and operational constraints.
- Explicit exclusions and non-goals.
- Assumptions that affect design.
- Open questions whose answers could change scope, safety, or architecture.

Do not silently turn ambiguity into product policy. Record low-impact assumptions; ask the product owner about decisions that change user behavior, data handling, permissions, or substantial scope.

Create a coverage map from each requirement to one or more planned outcomes and their eventual verification. This makes missing requirements visible before coding begins.

### 2. Discover the repository and runtime

Before finalizing implementation issues, inspect the actual project. Find its project instructions, existing architecture, data models, UI and API patterns, tests, build and run commands, deployment assumptions, and work already present. Record what can be reused and any constraints that affect decomposition.

Do not invent paths, scripts, services, APIs, or conventions. If a project is not yet available, label the design as provisional and make repository discovery the first work item. Do not claim a command is supported until it is found in project documentation or configuration.

### 3. Design the implementation

Describe the smallest useful architecture needed to satisfy the requirements. Identify components, data ownership, interfaces, error behavior, and shared prerequisites. Define contracts before assigning concurrent work that crosses them. Keep design proportional: avoid introducing infrastructure or abstractions without a requirement or repository need.

Mark design choices as confirmed, inferred, or unresolved. Explain material risks and how the plan reduces them. A technical design is a planning aid, not permission to broaden product scope.

### 4. Decompose into milestones and GitHub issues

Use four connected levels:

| Level | Meaning | Example |
|---|---|---|
| Requirement | Outcome the application must provide | Researchers can record wildlife sightings |
| Milestone | Coherent deliverable grouping outcomes | Record and inspect sightings |
| GitHub issue / change set | Bounded implementation unit | Save a sighting with validated species, time, and location |
| Verification | Evidence the change works | Integration check confirms valid data persists and invalid coordinates are rejected |

Prefer **vertical slices** for ordinary feature work: one useful behavior across the UI, service, and data layers it actually needs. This exposes integration issues early and yields user-visible progress. Create a separate horizontal GitHub issue when work is a real shared prerequisite (for example, a data migration, common authentication mechanism, or agreed API contract), not merely because code is organized by layer.

Split a behavior into multiple GitHub issues/change sets when different outcomes can be implemented and verified independently or when a prerequisite must land first. Combine related details in one issue when they are tightly coupled and together form one testable outcome. Do not create issues for trivial implementation details unless they address a distinct bug or risk.

### 5. Use a consistent GitHub issue/change-set schema

Every implementation GitHub issue (the change set) should include:

```markdown
## <Short outcome-focused title>
- GitHub issue: <number and URL, once created>
- ID: <stable identifier>
- Milestone: <milestone>
- Status: planned
- Priority: <ordered value or label, defined by this project>
- Depends on: <GitHub issue IDs, or none>
- Blocks: <GitHub issue IDs, or none>
- Parallel group: <group or serial>
- Requirement links: <requirement IDs>
- Scope: <one coherent outcome>
- Context: <relevant discovered architecture and conventions>
- Inputs/contracts: <interfaces or artifacts this work consumes>
- Outputs/contracts: <interfaces or artifacts this work provides>
- Acceptance criteria:
  - Given/when/then or otherwise observable conditions
- Verification:
  - Checks and expected evidence; name commands only if discovered
- Regression constraints: <important existing behavior to preserve>
- Out of scope: <nearby work not included>
- Risks/open questions: <or none>
- Change-set gate: <gate ID/name and related issue IDs, flag owner/key, default off, tester cohort, rollout steps, rollback/disable action, removal condition; or none if no gate is needed>
- Agent handoff: <task-specific context and constraints>
```

An issue/change set is ready only when its objective is singular, boundaries are explicit, dependencies are met or named, acceptance criteria are observable, and a reasonable verification method exists. Aim for work completable in a small number of agent attempts; if the agent must redesign broad areas or make product decisions, split the issue or resolve the ambiguity first. Create and maintain the planned issues in GitHub when repository access permits; otherwise produce issue-ready descriptions with stable IDs and clearly state that they have not been created.

### 6. Validate the issue plan before dispatch

Review the plan against these checks:

- **Coverage:** Every requirement maps to planned behavior and verification; no requested outcome was dropped.
- **Traceability:** Each GitHub issue links back to requirements and milestones.
- **Feasibility:** Work matches what repository discovery found; unknowns are explicitly provisional.
- **Boundaries:** Issues/change sets have one outcome, clear in-scope/out-of-scope lines, and observable acceptance criteria.
- **Dependencies:** Every prerequisite is explicit, and the graph has no cycles or missing nodes.
- **Contracts:** Concurrent work has agreed inputs and outputs; integration work is planned.
- **Verification:** Tests, checks, or functional QA are defined at the level appropriate to the risk.
- **Proportionality:** No unnecessary features, issues, abstractions, or parallel agents were added.
- **Risk:** Security, data migration, external integration, and destructive behavior receive appropriate sequencing and review.

If validation fails, revise the issue plan before assigning implementation work. Keep unresolved product decisions visible instead of hiding them in issue prose.

### 7. Execute GitHub issues on `main` in dependency-aware order

Treat GitHub issues as a directed acyclic graph. An issue/change set is **ready** when all required predecessor issues are complete and its contracts and environment are available. Among ready issues, prioritize work that unlocks the most useful downstream behavior or reduces the greatest risk.

Because this workflow has no feature branches, serialize all write-capable coding work on `main`: one coding agent at a time may modify the checkout. Other agents may do read-only discovery or review, but must not make concurrent edits. Keep each change small, review it, run the checks available before integration, and integrate it into `main` before assigning the next mutating task. Do not create feature branches or worktrees as a workaround. This trades parallel code editing for a simpler single-trunk history and lower integration ambiguity.

Give each agent one GitHub issue/change set at a time, with repository instructions, contracts, exclusions, verification expectations, its applicable change-set gate (if any), and reporting format. By default the change set is one issue; group multiple issues under one gate only when they intentionally must be validated/released together. Do not create a flag for every feature or issue by default. Ask the agent to inspect actual project conventions, make the scoped change, run relevant discovered checks, and report changed files, evidence, deviations, and blockers. Do not ask the agent to choose new product requirements. Changes to `main` should use the repository's actual review and commit controls; this guide does not assume a specific push or deployment mechanism.

Integrate completed work incrementally. Re-check dependent issues after upstream changes and update the graph and issue status as reality changes. If a change fails checks or cannot be safely integrated, stop and correct it on the same trunk before continuing. Paths that belong to a gated change set remain dark for ordinary callers until that change set is ready; do not infer that every new capability requires its own gate.

### 8. Verify implementation and completion

Use layered verification:

1. **Task-level:** Did the agent stay within scope, follow project guidance, and report actual evidence?
2. **Repository-level:** Do relevant tests, static checks, build checks, and review meet the project's existing standards? Do not invent or claim commands/results.
3. **Functional:** Does the changed behavior work through meaningful user paths, including important error cases? Prefer tests that exercise real code paths and assert actual outputs where practical.
4. **Integration/regression:** Do connected slices work together, and do existing important behaviors remain intact?
5. **Requirement-level:** Does the finished application satisfy every original requirement, including constraints and exclusions?

The manager should distinguish passed, failed, blocked, and not run. A GitHub issue/change set is complete only when its acceptance criteria are met, required verification has evidence, the scoped result is reviewed/integrated according to the workflow, and status records any remaining limitation. The project is complete only when all required outcomes are covered, end-to-end integration is verified, and remaining gaps are clearly reported.

## Production-only feature testing and release

Production is the only deployed test environment in this workflow. Use a **change-set release gate** when an incoming issue/change set is not yet trusted for general callers. A gate may cover multiple related issues when they are intentionally tested and released together; it is not a one-flag-per-feature policy. Do not gate already trusted behavior by default. Treat each gate enablement as a production change with a named owner, a narrow audience, observable success criteria, and a disable/rollback action. The feature-flag platform and deployment controls are not specified here; discover the actual mechanisms and access controls before implementation.

### Flag design and access

- For every gated change set, default the **entire gated change set** to off for ordinary callers. Enforce the gate on trusted server-side paths where possible; hiding a UI element alone is not access control. A new feature only needs to be behind a gate when it is part of an untrusted/incoming change set or has another explicit rollout need.
- Give authorized testers an explicit allowlist or controlled cohort tied to authenticated identities/roles. Do not use a guessable URL parameter, client-controlled header, or public flag key as authorization.
- Limit tester access to named accounts or a narrowly managed group. Check all entry points (UI, API, background jobs, notifications, exports) so callers cannot reach the feature through an unguarded path.
- Make flag evaluation observable: record flag/config version and whether the feature path was selected, without logging secrets or unnecessary personal data. Distinguish tester traffic from ordinary traffic in metrics and logs.
- Give each change-set gate an owner, included GitHub issue/change-set scope, default, tester cohort, rollout steps, disable action, and removal condition. Keep gate membership explicit as changes are added or removed. Remove the temporary gate and dead paths after full release and the agreed observation period.

### Safe test data and side effects

- Prefer dedicated production test accounts and clearly tagged synthetic records. Testers should be able to identify and clean up test data without affecting customer data.
- Define permitted production side effects before testing: emails, push notifications, payments, external API calls, analytics, exports, and irreversible writes. Suppress, sandbox, or route them safely when possible; a tester-only flag does not automatically prevent these effects.
- Do not use real customer data for destructive, privacy-sensitive, financial, safety-critical, or irreversible test cases. If behavior cannot be validated safely with synthetic data and reversible actions, block it for a human decision and design another verification method.
- For schema/data changes, prefer backward-compatible expand-and-contract sequencing: deploy additive compatible changes first, keep old and new code paths compatible, migrate safely, and remove obsolete structures only after verified use has ended. Define recovery or compensation steps for data-changing work.

### Production validation and staged release

Plan these stages and explicit pass/stop conditions for each gated change set. Each included issue links to its gate and defines the evidence it contributes; do not require an independent flag for every feature or issue:

1. **Pre-deployment checks:** Run available unit, static, build, security, and migration checks before code reaches `main`/production. Production-only means there is no separate deployed test environment; it does not mean skipping automated checks that do not require one. Review the exact production flag configuration expected after deployment.
2. **Dark deployment:** Deploy with the flag off for ordinary callers. Confirm health checks, startup, error rates, resource use, flag evaluation, and compatibility. Exercise non-user-visible paths only when this cannot cause uncontrolled side effects.
3. **Tester-only enablement:** Enable the flag for the authorized tester cohort. Verify the intended journey with synthetic/test data. Check functional outcomes, authorization boundaries, logs/metrics, latency, errors, and dependencies. Record the flag/config version, test account, time window, outcomes, and any cleanup.
4. **Limited release:** After tester evidence passes, expose the feature to a small, controlled cohort or percentage if supported. Compare feature-specific and overall health signals against agreed thresholds and a suitable control/baseline. Keep the evaluation window long enough for relevant usage; do not advance on insufficient traffic or noisy, overly aggregated metrics.
5. **Progressive rollout:** Expand in predeclared steps only while success criteria remain satisfied. Pause or disable immediately if a stop condition occurs. Maintain a named owner and response path during rollout.
6. **General release and cleanup:** Enable for the intended audience only after rollout evidence is accepted. Continue monitoring for the agreed period, then remove the release flag and obsolete code paths in a planned `main` change.

Choose rollout percentages and observation windows based on traffic, potential impact, and flag-system capabilities; there is no universal safe percentage. If there is no reliable cohorting, monitoring, or rapid disable mechanism, do not claim a safe progressive rollout. Reduce exposure, add the missing controls, or defer release.

### Required stop and recovery plan

Each production-test issue/change set must state:

- Who may enable and disable the flag.
- The exact disable/rollback action and how quickly it takes effect.
- Metrics, logs, and user-visible signals to watch, with thresholds or decision rules.
- Conditions that halt the test, such as elevated errors or latency, resource pressure, data-integrity problems, authorization bypass, unexpected side effects, or support reports.
- Whether disabling the flag is sufficient, or whether code rollback, data repair, or incident response is also needed.
- How test records and side effects will be identified and cleaned up.

Test the kill switch before relying on it. A flag cannot undo writes or side effects already performed. Keep deployed code compatible with both flag states and make rollback safe for the current database and clients. If a stop condition occurs, disable the feature or roll back first to contain impact, then investigate.

Google SRE recommends canary evaluation against a control using fine-grained metrics and warns that shared dependencies and data can let a canary affect the control. Its guidance emphasizes small, time-limited exposure and a rapid rollback path. ([Canarying Releases](https://sre.google/workbook/canarying-releases/); [Monitoring Systems with Advanced Analytics](https://sre.google/workbook/monitoring/))

## Make agent work verifiable

The most dependable approach is to make the agent's claims checkable by tools and evidence that do not depend on the same model simply judging its own output. The coding agent can help write tests, but tests authored in the same task are not independent proof: require them to run, inspect their assertions, and supplement them with existing project checks, independent review, and user-visible evidence. OpenHands' verification guidance similarly separates agent-run assessment, repository review, and functional QA; its QA agent exercises changed behavior and returns evidence such as commands, outputs, and screenshots. ([The Verification Stack](https://www.openhands.dev/blog/20260506-the-verification-stack))

### Recommended layers

1. **Deterministic checks on every `main` change:** Run the repository's existing formatter/linter, type checker, unit tests, build, dependency/security checks, and database migration validation where they exist. Make the results visible and retain logs. These checks catch many defects without deploying or using a second runtime environment.
2. **Behavioral acceptance tests:** For each issue, encode important acceptance criteria as executable tests with concrete inputs and assertions on outputs, state changes, permissions, and errors. Prefer real application code paths and a disposable local/test fixture where the check does not require production. Avoid tests that only assert mocks were called.
3. **API contract and workflow checks:** Keep an OpenAPI/GraphQL schema accurate if the project uses one. Run ordinary positive/negative API examples and stateful user workflows. Use [Schemathesis](https://schemathesis.readthedocs.io/en/stable/) for schema-derived property-based checks: it generates edge cases, sequences linked operations, and emits reproducers. It is a strong candidate when a machine-readable API schema exists; it is not proof of business correctness, authorization policy, or data safety.
4. **UI journey checks:** Use [Playwright](https://playwright.dev/) to automate user-visible journeys with role/label-based locators and assertions on what users see and can do. Capture screenshots and traces on failure so a reviewer can inspect the browser state, DOM snapshots, network activity, and action history ([Trace Viewer](https://playwright.dev/docs/trace-viewer)). Test key error, loading, empty, permission-denied, and gated/ungated change-set states as well as the happy path.
5. **Accessibility checks:** Integrate [axe-core](https://github.com/dequelabs/axe-core) into Playwright journeys to catch common WCAG issues in rendered states. It does not detect every accessibility problem; include keyboard and screen-reader/manual review for important flows. Activate menus, dialogs, and other hidden states before scanning them.
6. **Independent change review:** Use a reviewer distinct from the implementation agent where practical, with a structured checklist for correctness, security, privacy, migrations, regression risk, and whether the tests actually prove the acceptance criteria. Treat LLM review as advisory; deterministic tests and a human review remain important for high-impact changes.
7. **Production tester evidence:** Since production is the only deployed test environment, record the exact `main` commit/build, change-set gate and flag config/version, tester identity/cohort, synthetic test-data IDs, time window, steps, expected and observed result, screenshots/trace or request/response evidence, key health metrics, and cleanup. Avoid recording credentials, tokens, or unnecessary personal data.

### Tools worth considering

| Need | Candidate | Best fit and limits |
|---|---|---|
| OpenHands-native agent/repo verification | OpenHands Critic plus `code-review` and `qa-changes` extensions | The Critic evaluates agent progress; repo review checks diffs; QA runs changed behavior through browsers, CLI, and HTTP and reports evidence. The extensions are open source. The Critic's availability depends on the OpenHands deployment/product. The published QA flow is PR-oriented, so for trunk-only development trigger equivalent checks after deployment or make the agent run the QA workflow against the tester-enabled production cohort. These layers assist; they do not replace hard assertions or human judgment. ([Verification Stack](https://www.openhands.dev/blog/20260506-the-verification-stack); [OpenHands Extensions](https://github.com/OpenHands/extensions)) |
| Browser/UI regression | Playwright | Mature browser automation and test runner; model-agnostic. Best for repeatable journeys, assertions, screenshots, and traces. A coding model can author tests, but it cannot make a weak assertion strong: review locators and expected outcomes. ([Playwright docs](https://playwright.dev/docs/intro); [Trace Viewer](https://playwright.dev/docs/trace-viewer)) |
| UI accessibility | axe-core, integrated with Playwright | Adds automated accessibility rule checks to rendered states; catches only a subset of issues, so retain manual keyboard/accessibility review. ([axe-core](https://github.com/dequelabs/axe-core)) |
| API schema/edge cases | Schemathesis | Strong default when the API has OpenAPI or GraphQL schema. Property-based inputs and stateful operation chaining find schema violations and server errors; business-specific expectations still need explicit tests. ([Schemathesis](https://schemathesis.readthedocs.io/en/stable/)) |
| Deep stateful REST fuzzing | Microsoft RESTler | Research-backed stateful fuzzing from OpenAPI, with published peer-reviewed work. Potentially powerful but can create resource leaks, performance degradation, or data corruption. Do not run aggressive fuzzing against production. Use only in an isolated disposable environment or a carefully restricted, explicitly approved, non-mutating setup. ([RESTler repository and safety notes](https://github.com/microsoft/restler-fuzzer)) |

These tools are established, model-agnostic software verification tools. Their maturity should not be confused with proof that a particular open-weight coding model uses them effectively. I did not find evidence that the tools above have all been benchmarked specifically with OpenHands plus open-weight models. Their advantage is that their checks are reproducible regardless of which model wrote the change. To evaluate model-specific performance, run the same fixed set of GitHub issues/change sets and verifier against each candidate model, retain failures and traces, and compare acceptance-test pass rates, regressions, false alarms, and human review time. Do not select an agent based only on the tests it writes for itself.

### Production-only limits on automated testing

- Keep routine Playwright/API smoke checks on production to a small, known set of deterministic scenarios using authorized tester accounts and synthetic records. Run them only after confirming the target build and flag cohort.
- Route all mutations to tagged test data and clean it up. Use idempotency keys or safe repeatable setup where the application supports them. Avoid triggering real emails, payments, external actions, or irreversible operations unless explicitly controlled.
- Run property-based API testing and fuzzing against production only if requests are tightly allowlisted, rate-limited, data-isolated, reversible, and approved by the production owner. Otherwise run those tools offline against a local process/fixture, or defer that class of test; never point unconstrained fuzzers at production.
- Keep production test credentials narrowly scoped and out of agent prompts/logs when possible. If agents need to execute tests, supply short-lived, least-privilege credentials through the existing secret mechanism, and make sure traces, screenshots, HARs, and logs do not expose secrets or personal data.
- Make the verification artifact part of issue/change-set completion. A statement such as “tested in prod” is insufficient without the build/gate cohort, steps, results, and relevant evidence.

### Verification handoff template

```markdown
## Verification record
- GitHub issue/change-set and requirement IDs:
- `main` commit/build:
- Flag/config version and cohort:
- Automated checks run: <name, result, link/log>
- UI/API scenarios: <account type, synthetic data IDs, steps>
- Expected vs observed:
- Evidence: <screenshots, Playwright trace, request/response, logs>
- Production health signals and observation window:
- Side effects and cleanup:
- Not tested / limitations:
- Reviewer and decision:
```

## Worked example

Requirement: “Researchers can record sightings, attach photos, view them on a map, and filter by species and date.” This is illustrative; actual GitHub issues depend on repository discovery.

| GitHub issue / change set | Outcome | Dependencies |
|---|---|---|
| A | Discover existing storage, location, upload, and map patterns; report constraints | None |
| B | Define the sighting fields and API/UI contract based on existing conventions | A |
| C | Implement the record/view slice; if not yet trusted, gate this issue's complete change set | B |
| D | Attach an allowed photo to a saved sighting; gate this issue's complete change set if not trusted, with side-effect controls | C; may follow a storage contract |
| E | Filter sightings by species and date with clear empty/error states; gate this issue's complete change set if not trusted | B |
| F | Display saved sightings on a map using the established location format; gate this issue's complete change set if not trusted | C and map integration contract |
| G | Verify tester authorization, the end-to-end journey, production signals, stop/disable procedure, and cleanup | C, D, E, F |

Each row is a planned GitHub issue and its implementation change set. The first issue is discovery, not a guess at file names. B is a shared contract prerequisite. Under trunk-only development, write-capable implementation stays serialized on `main` even where the graph shows logical independence. Each untrusted issue can be tested behind its own change-set gate; related issues may share one gate only when the plan explicitly treats them as one release batch. G includes production tester access and safety evidence; it does not replace issue-level checks for C–F.

## Reusable planning prompt

> Act as the planning manager for this application. First extract requirements and constraints, then inspect the actual repository and instructions before finalizing implementation details. Do not invent paths, APIs, commands, or architecture. Produce a requirement coverage map, concise design with confirmed/inferred/open decisions labeled, and a dependency-aware set of GitHub issues using this guide's schema. Each GitHub issue is one bounded change set for one coding assignment, with acceptance criteria and verification evidence. Prefer verifiable vertical slices. This project uses trunk-only development on `main`, with no feature branches and one write-capable coding agent at a time. Production is the only deployed test environment. When an issue/change set is not trusted for ordinary callers, gate that entire change set behind a default-off, server-enforced feature flag and test it with a restricted production cohort. A gate may cover several related issues only when they are intentionally validated/released together; never require one flag per feature, and do not gate trusted changes by default. Plan synthetic data, monitoring, rollout stages, stop conditions, disable/rollback, and gate removal. Validate requirement coverage, dependencies, issue scope, production safety, and risks. Do not dispatch coding work until the plan is internally consistent; surface product decisions that need a human answer.

## Source articles

- OpenHands, [Automating Massive Refactors with Parallel Agents](https://hub.openhands.dev/blog/automating-massive-refactors-with-parallel-agents), October 9, 2025.
- Jiayi Geng / OpenHands, [Effective Strategies for Asynchronous Software Engineering Agents](https://hub.openhands.dev/blog/asynchronous-software-engineering-agents), April 27, 2026.
- OpenHands, [Learning to Verify AI-Generated Code](https://www.openhands.dev/blog/20260305-learning-to-verify-ai-generated-code), March 5, 2026.
- OpenHands, [The Verification Stack](https://www.openhands.dev/blog/20260506-the-verification-stack), June 22, 2026.
- OpenHands, [What Are Coding Agents? A Developer's Guide to Agentic Coding](https://hub.openhands.dev/blog/what-are-coding-agents), June 2, 2026.
- Martin Fowler, [Dark Launching](https://martinfowler.com/bliki/DarkLaunching.html).
- Martin Fowler, [Feature Toggles (aka Feature Flags)](https://martinfowler.com/articles/feature-toggles.html).
- Google SRE Workbook, [Canarying Releases](https://sre.google/workbook/canarying-releases/) and [Monitoring Systems with Advanced Analytics](https://sre.google/workbook/monitoring/).
- Playwright, [Test documentation](https://playwright.dev/docs/intro) and [Trace Viewer](https://playwright.dev/docs/trace-viewer).
- Schemathesis, [Documentation](https://schemathesis.readthedocs.io/en/stable/).
- Microsoft, [RESTler](https://github.com/microsoft/restler-fuzzer).
- Deque, [axe-core](https://github.com/dequelabs/axe-core).
- OpenHands, [Extensions repository](https://github.com/OpenHands/extensions).
