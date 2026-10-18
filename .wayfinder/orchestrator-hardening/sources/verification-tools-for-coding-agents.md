# Evaluate Verification Tools for Coding-Agent Work

## Purpose

Use this brief with a coding session to investigate how to strengthen the project's **reviewer and especially tester agent**. The goal is to make agent changes verifiable with repeatable evidence. First inspect the real repository, current agent instructions/workflows, test setup, deployment path, and feature-flag system. Then recommend a minimal integration plan or implement it if the task explicitly asks for implementation. Do not assume a language, framework, API schema, CI provider, OpenHands extension, or file path.

## Project constraints to preserve

- Development is trunk-only on `main`; there are no feature branches. Serialize write-capable coding-agent work on `main`.
- Production is the only deployed runtime test environment.
- When a coherent incoming change set is not trusted for ordinary callers, deploy that whole set dark behind a default-off, server-enforced **change-set release gate** implemented with a feature flag. One gate can cover multiple tickets/features; do not assume one flag per feature, and do not gate already trusted changes by default. Authorized testers enable the gated set for a restricted cohort before gradual release.
- Do not run unconstrained API fuzzing or destructive tests against production. Production checks must use controlled tester accounts, synthetic/tagged data, bounded requests, and an explicit cleanup/disable plan.
- Deterministic checks that do not require a deployed test environment (unit tests, static checks, builds, schema validation) should still run before deployment where available.
- Never claim checks passed unless their results were observed. Treat LLM-generated tests and LLM review as useful but not independent proof.

## Candidate verification stack

### 1. OpenHands reviewer and QA capabilities

Inspect whether the project already uses OpenHands' verification features or extensions:

- **OpenHands Critic:** agent-level signal about whether a coding run is likely succeeding; useful for catching off-track or failing runs, but not a substitute for tests.
- **`code-review` extension:** structured review of correctness, security, testing gaps, and dependency risk.
- **`qa-changes` extension:** runs changed behavior through the application using browser, CLI, or HTTP paths and reports evidence such as commands, outputs, and screenshots.

The documented OpenHands workflow is PR-oriented. Because this project has no feature branches, determine how the equivalent QA should run after a `main` deployment and against the tester-enabled production cohort. Do not add PR assumptions that conflict with trunk-only development. Verify current extension names, setup, licensing, and supported trigger modes from the upstream sources before recommending integration.

Sources: [OpenHands Verification Stack](https://www.openhands.dev/blog/20260506-the-verification-stack), [OpenHands Extensions](https://github.com/OpenHands/extensions).

### 2. UI verification: Playwright

If the application has a browser UI, evaluate [Playwright](https://playwright.dev/) as the default candidate for deterministic user journeys. Favor accessible role/name/label locators and assertions on visible behavior, not brittle CSS selectors or implementation details. Cover the important happy path and permission-denied, loading, empty, and error states. Capture screenshots and traces for failures so a reviewer can see the actions, page snapshots, and network activity ([Trace Viewer](https://playwright.dev/docs/trace-viewer)).

For production-only runtime checks, run a small, fixed set of approved journeys after confirming the deployed `main` build and the applicable change-set gate/tester cohort. Use least-privilege tester accounts and synthetic/tagged records. Avoid payments, real notifications, irreversible actions, or unbounded loops. Ensure artifacts do not expose credentials or unnecessary personal data.

### 3. Accessibility: axe-core

Evaluate integrating [axe-core](https://github.com/dequelabs/axe-core) into Playwright or the existing browser-test framework. Run it against meaningful rendered states, including dialogs and menus after they are opened. Automated accessibility checks catch common issues, not every WCAG failure; retain keyboard checks and human review for important flows.

### 4. API behavior: Schemathesis

If the project exposes OpenAPI or GraphQL, evaluate [Schemathesis](https://schemathesis.readthedocs.io/en/stable/) for schema-derived property-based testing, edge cases, and stateful operation workflows. Confirm that the schema accurately represents the API. Add explicit tests for domain rules, authorization, privacy, and data integrity; schema conformance cannot prove those policies.

For production, keep API checks to a bounded, reviewed smoke suite unless there is a carefully isolated and explicitly approved test namespace. Generated property-based requests can mutate data, so do not point a default fuzzing run at production.

### 5. Deeper REST API fuzzing: RESTler

Consider Microsoft's [RESTler](https://github.com/microsoft/restler-fuzzer) only if the API is REST/OpenAPI and the project can provide an isolated disposable target or a genuinely safe, bounded setup. RESTler has peer-reviewed research behind its stateful fuzzing approach, but aggressive runs can create resource leaks, degraded performance, or corrupted data. It is **not** a default production-testing tool.

## Recommended verification design

Ask the coding session to map the existing verification system into these layers and identify gaps:

1. **Pre-deployment deterministic checks:** existing unit/integration tests, lint/type/build/security checks, and migration validation that can run without a deployed test environment.
2. **Issue acceptance tests:** executable assertions tied to each GitHub issue/change set's criteria, including important negative cases. Review test quality; test presence alone is not evidence.
3. **Independent reviewer:** a structured code review that checks scope, behavior, security/privacy, migrations, regression risk, and whether tests prove the issue's criteria. LLM findings are advisory; high-impact work still gets appropriate human review.
4. **Functional tester:** run actual changed UI/API behavior and return evidence, not just a pass/fail claim.
5. **Production tester cohort:** use the production-only steps in the project's release process: verify the exact build and change-set gate/config version, enable the whole gated set only for authorized testers, use synthetic data, observe agreed metrics, stop on predeclared failure conditions, and clean up test data.

For each verification run, preserve a compact record:

```markdown
## Verification record
- GitHub issue/change-set and requirement IDs:
- `main` commit/build:
- Change-set gate ID/scope, flag/config version, and tester cohort:
- Automated checks and results:
- UI/API scenarios and steps:
- Expected vs observed result:
- Evidence links: screenshots, trace, request/response, logs
- Production signals and observation window:
- Test-data identifiers and cleanup:
- Checks not run / limitations:
- Reviewer decision:
```

## Questions for the coding session to answer

- Which OpenHands reviewer/tester agents, extensions, skills, or workflows are already present? What do they actually execute today?
- Can the tester produce reliable UI evidence (screenshots/traces) and API evidence (request/response, assertions, logs)? What is missing?
- What is the current UI framework and browser-test setup? Is there an API schema suitable for Schemathesis or RESTler?
- How can a post-deploy tester safely target a specific `main` build and restricted change-set gate cohort for the relevant issue/change set?
- What secrets, permissions, production side effects, rate limits, and cleanup controls are required?
- Which checks should block deployment or gate progression, and which should be advisory? How will results be retained and linked to a GitHub issue/build?
- Which one or two changes provide the largest improvement with the least new infrastructure?

## Expected output

Return:

1. A brief inventory of the repository's current reviewer, tester, UI/API test, deployment, and flag capabilities, with verified paths and commands.
2. A recommendation ranked by value, effort, and production risk, distinguishing deterministic gates from LLM-assisted review.
3. A concrete integration plan compatible with trunk-only `main` and post-deploy tester validation of a change-set gate. Do not propose one flag per feature by default.
4. If implementation is requested, a focused change plus observed verification results and any production checks that must be performed by an authorized tester.

Do not introduce every candidate tool by default. Recommend only what fits the actual stack and closes a demonstrated gap. Keep destructive or exploratory tests off production unless their safety controls are established and approved.

## References

- OpenHands, [The Verification Stack](https://www.openhands.dev/blog/20260506-the-verification-stack)
- OpenHands, [Extensions repository](https://github.com/OpenHands/extensions)
- Playwright, [Test documentation](https://playwright.dev/docs/intro) and [Trace Viewer](https://playwright.dev/docs/trace-viewer)
- Deque, [axe-core](https://github.com/dequelabs/axe-core)
- Schemathesis, [Documentation](https://schemathesis.readthedocs.io/en/stable/)
- Microsoft, [RESTler](https://github.com/microsoft/restler-fuzzer)
- Google SRE Workbook, [Canarying Releases](https://sre.google/workbook/canarying-releases/) and [Monitoring Systems with Advanced Analytics](https://sre.google/workbook/monitoring/)
