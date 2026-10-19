---
title: Flag Lifecycle: flag-off and flag-on tests are checked, and a retirement removes them
type: task
status: resolved
assignee: ojones
blocked_by: [08b-deterministic-flag-name-and-creation.md]
---

## Question

Make dark mode unit tested by a deterministic check (STEP 4.4, 5.4). (1) The Starter gets a test helper `withFlag(slug, on, fn)` and an `npm run check` step (an ESLint rule or a small script, with cases in `agents/lint-fixtures/cases.json` run by `starter_lint_test.py`) that fails when a slug in `flags.json` lacks a `withFlag(slug, false, ...)` test or a `withFlag(slug, true, ...)` test, or has more than one `isFeatureEnabled` entry point. The pre-review `npm run check` (`limits.precheck`) already runs it, so a miss goes back to the coder at no review cost; it reaches existing apps through template sync. (2) The retirement verifier (`retirement_check`) is extended to scan test files and `flags.json` as well as source, ignoring only comments, and the retirement block tells the coder to delete the `withFlag(slug, false)` tests and unwrap the `withFlag(slug, true)` ones. A codemod that does this mechanically stays a later ticket.

## Added context

Source plan: "Changes 10". Touches `templates/starter/`, so a template-sync Update App Intake follows for every app: do it once, with the other Starter changes of the redesign, and say so in the resolution. Reviewer flag findings (`flag_findings`) stay in the Build Run's review.

## Resolution (2026-10-19)

`ruff check` clean, 588 tests OK (3 skipped), `boundary_test` and `flow_spec_test` pass; the Starter's own suite (vitest 11 tests, eslint, `tsc`, `check-flags`) passes. Not committed. **Not yet run live**: the proof is the first update that reaches an app through template sync.

**What changed.**
- **`templates/starter/scripts/check-flags.mjs`** (a small script, not an ESLint rule: a rule sees one file, this needs `flags.json` and every test together). For each slug in `flags.json` it fails when there is no `withFlag(slug, false, ...)` test, no `withFlag(slug, true, ...)` test (comments ignored), or when the slug is checked with `isFeatureEnabled` in more than one non-test place. `npm run check` now ends with it, so the pre-review check (`limits.precheck`) sends a miss back to the coder at no review cost. `--stdin` mode takes `{slugs, files}` so cases need no repo.
- **`withFlag(slug, on, fn)`** in `backend/src/__tests__/with-flag.ts` (with its own test): sets an in-memory provider with the kill switch on and the slug on or off, runs `fn`, and puts the previous provider back even when `fn` throws.
- **The script is the Orchestrator's:** added to `PROTECTED` and `TEMPLATE_FILES_HELD`, so a coder commit that touches it is rejected and template sync copies it in with the lint config, pushed together with the coder's fixes (never alone). `package.json` (the `check` line) reaches an app through the template-sync coder's merge, as other `package.json` changes do.
- **Retirement verifier.** The retirement grep already covers the whole tree, so tests (`withFlag("slug", ...)`) and `flags.json` already counted as references; `retirement_check` now says so, its message tells the coder to delete each `withFlag(slug, false, ...)` test and unwrap each `withFlag(slug, true, ...)` test, and a test proves tests and the manifest count while comments do not. The coder prompt says the same, and also tells the coder to write both tests for a flagged change; `templates/starter/AGENTS.md` too.
- **Cases:** eight `flagCases` in `agents/lint-fixtures/cases.json` (clean, no flags, no tests, only on, only off, another slug's tests, tests in a comment, two entry points), run by `starter_lint_test.py`, which also checks `npm run check` runs the script. INV-53 added with a test. `ARCHITECTURE.md`, `STANDARDS-FEATURE-FLAGS.md`, the flow spec (4.4) and the orchestrator map say Built.

**Template sync, once.** This changes `templates/starter/`, so every app needs a template-sync Update App Intake. Do it once, with any other Starter changes of the redesign, not per ticket. An app that already has flags in `flags.json` without both tests will fail `npm run check` after the sync; the template-sync coder adds the tests (the check says which).

**Left for later.** A codemod that retires the tests mechanically stays a later ticket. A Starter test file that calls `withFlag` is not checked for asserting something inside the callback beyond the existing `test-asserts` rule.
