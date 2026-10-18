---
title: Give the one tester deterministic check tools, including a headless browser
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

The tester verifies a Managed App with `curl` and its own judgement. Two weaknesses follow: it misjudges (the seeded-bug benchmark in ticket 07 found it catches gross faults and misses edge cases about half the time, including calling 200 a pass where the spec says 201), and it cannot see anything a browser would (rendering, forms, navigation, what a flagged UI change looks like). How should the single tester agent be given better tools, without splitting it into several agents?

Decide: (a) **declarative check helpers owned by the Factory**, which the tester calls instead of writing its own scripts: `api-check` (takes expected status and body fragments, makes the request, returns observed against expected) and `ui-check` (a Playwright step list using role and label locators, returns observed text and state plus screenshots). The model chooses *which* checks the spec calls for and states the expectation; the helper observes, and the Orchestrator decides pass or fail from observed against expected, not from the model's say-so. (b) whether `ui-check` is part of the same tester invocation, run only when the change touches `frontend/` or the spec mentions a screen, or a second invocation of the same role; the default is one agent. (c) how the browser is installed on the runner, kept out of the Managed App (no change to its lockfile or Docker image), and pinned. (d) evidence hygiene: Managed App repos are public, so uploaded Actions artifacts are public, and a Playwright trace or HAR records request headers and cookies including the Preview Token. Decide what is uploaded (screenshots and extracted text yes; traces only scrubbed, or not at all). (e) which UI fixtures to add to `agents/smoke-tester/` (a missing label, wrong text, a flagged control that should be hidden) so the browser tool is measured the same way as the API one.

## Added context

- Out of scope in the map until now ("Playwright, axe-core ... until a measured gap or a real UI exists"). The measured gap now exists for the API side (ticket 07). For the UI side no Managed App has a real UI yet: `ojones-todo` is API-only apart from the Starter Template's placeholder page. A UI test bed is needed first; an Update Intake adding a small page to `ojones-todo` would provide it (and exercise the planner on a frontend change).
- The advice documents recommend Playwright with role and label locators, screenshots on failure, axe-core scans of rendered states, and keyboard and manual review for what automation misses (`docs/advice/verification-tools-for-coding-agents.md`).
- The app already supports a browser carrying the Preview Token: `?preview=<token>` sets an HttpOnly cookie (`STANDARDS-FEATURE-FLAGS.md`, Preview), so a browser session can see dark UI without special setup.
- The tester's peak context is the thing to watch: browser output is large, and the context goal is 100k tokens.
- Suggested order: `api-check` first (no browser, directly addresses the misjudging seen in ticket 07, measurable with the existing harness); then a UI test bed; then `ui-check`.

## Resolution

(a) `api-check` (INV-30) and `ui-check` (INV-36): the tester states expectations as data, a Factory helper observes and logs, the Orchestrator reconciles so the helper's log outranks the model. (b) One tester, one invocation; the browser instructions appear only when the change touches `frontend/` or the spec mentions a screen. (c) Playwright and Chromium pinned in `agents/playwright-version.txt`, installed by the workflow into `/opt/playwright`, outside the Managed App. (d) Screenshots of failing scenarios and the helper's JSONL log are uploaded; no traces or HAR files; the Preview Token is never printed, logged or screenshotted. (e) Not done, by choice: no UI fixtures in `agents/smoke-tester/` yet, so the browser tool's detection rate is not measured the way the API one was; the live test bed (a to-do page on `ojones-todo`) passed its second run. Add UI fixtures and measure when a miss in real use shows the need. Accessibility scans (axe-core) were not added.
