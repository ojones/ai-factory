---
title: Run the cheap deterministic checks before the reviewer, not only in CI
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

The reviewer now reads the coder's commit before anything is pushed, but the formatter check, the type-check, the linter and the secret scan only run in the Test Gate after the push, so a mechanical problem still costs a reviewer call (and, if it slips through, a push and a CI run) before anything notices. Should the Orchestrator run the fast checks on the local commit before the reviewer (`npm run format:check`, `npm run check`, and the diff scan for secret shapes from ticket 16), feed the failures straight back to the coder as findings, and keep the reviewer for what only judgement finds? The owner earlier asked that only the coder runs the formatter and the Orchestrator not duplicate it, so a check that only reads, never rewrites, is the version to weigh; is it worth the overlap with the Test Gate?

## Added context

- Precedent: the Orchestrator already makes findings that need no judgement (`flag_findings`, `suppression_findings`) and rejects commits for protected files or leftover retirement references before the reviewer sees them (`BuildRun.coder`).
- `npm run check` takes about 2.5 seconds today (tsc and ESLint); the build and the tests are slower and stay with the coder and CI.
- Constraint: the checks run in the app checkout, so they need the app's dependencies installed (the Orchestrator already runs `npm ci` at setup) and, with Agent isolation on, must not run app code as the Orchestrator's account; running them as the Agent user is the safe form.
- Decide the severity of what they find (a failing type-check is a hard stop, a formatting difference is not a gate, see STANDARDS-CODING.md) and whether a failure costs a round.

## Resolution (2026-10-14)

Decided as defaults and built; no live run.

- **What runs.** The Orchestrator runs the app's own `npm run check` (tsc and ESLint, about 2.5 s) on the coder's commit before the reviewer, as the Agent user with the coder's minimal environment, then restores the tree. Read-only; skipped when the app has no `check` script or it cannot be run (left to the Test Gate).
- **Not run.** `format:check` (a formatting difference is not a gate, and the owner wants only the coder to format), the build and the tests (slower; the coder and CI keep them). The secret-shape scan waits for ticket 16.
- **Severity and cost.** A failure is a hard stop for that commit: it is handled in the coder's rejection loop (`BuildRun.coder`), so the coder is told the errors and tries again, up to three attempts as with a protected-file violation, and it uses no review round, push or CI run. Three failures end the run for a person.
- **Overlap with the Test Gate.** Accepted: the Gate stays the authority; this only moves the cheapest failure earlier. Turn off with `limits.precheck: false`.

Unit-tested (`CheckProblem`). The cost saving is not measured; judge it with ticket 19.
