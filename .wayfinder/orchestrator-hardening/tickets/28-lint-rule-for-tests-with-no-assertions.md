---
title: A lint rule for tests that assert nothing
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

The first lint slice (ticket 15) catches a test that reads source text, asserts on `flags.json` or leaves `.only`. It cannot catch the most common test-quality finding: a test with no assertion, or only a weak one (`toBeTruthy`, `toBeDefined`), which cannot fail. Catching it needs more than a `no-restricted-syntax` selector. Should the Starter add `eslint-plugin-vitest` (its `expect-expect` rule) or a small custom rule, what does a root devDependency cost in every app (install time, Dependabot updates, a lock file the sync regenerates), and how are tests that assert through a helper function (for example an `expectStatus` helper) kept from false alarms?

## Added context

- Today this is the reviewer's judgement ("a test added for the change that cannot fail" is a blocking `test_quality` finding in `agents/prompts/reviewer-rubric.md`); a rule would move the clear cases to a check, which is the direction ticket 15 set.
- Constraints from ticket 15: the rule must be additive and precise, add failing and passing cases to `agents/lint-fixtures/cases.json` (run by `orchestrator/test_starter_lint.py`), stay fast (`npm run check` is about 2.5 seconds), and reach existing apps through template sync, where only the coder fixes what it reports; the lint config is the Orchestrator's, so the coder cannot loosen it.
- Weak matchers are a separate, more contentious choice: banning `toBeTruthy` and `toBeDefined` outright could make the coder fight the linter; consider a warning first or only flagging them as the sole assertion of a test.

## Resolution (2026-10-14)

Built; decided with defaults, not put to the owner.

- **A small rule in the Starter's `eslint.config.mjs`, not `eslint-plugin-vitest`.** It costs no dependency (no install time, no extra Dependabot updates, no lock file for the sync to regenerate), and the one thing the plugin adds that matters, recognising assertion helpers, is a name pattern here.
- **`factory/test-asserts` (error).** A test (`it`/`test`, including `it.each(...)`) whose body calls nothing that asserts. A call counts as an assertion when its name starts with `expect`, `assert`, `verify` or `should`, or it is a method on such an object (`assert.equal`, supertest's `.expect(404)`), so a helper like `expectStatus` is not a false alarm. `it.skip` and `it.todo` are ignored.
- **`factory/test-asserts-strongly` (warning).** A test whose only assertions are `toBeTruthy`/`toBeDefined`. A warning, not an error, so the coder does not fight the linter over a boolean it really means; ticket 20 can raise it with real data.
- **Known limit.** A helper that asserts inside but is not named like one (for example `runCase`) is reported; the message says to name it `expect*`/`assert*`.
- Eleven new cases in `agents/lint-fixtures/cases.json` (failing, passing, helpers, `it.each`, a non-test file); the Starter's own tests lint clean. The reviewer rubric now leaves the no-assertion case to the linter. Existing apps get it through template sync. Not yet run against `ojones-todo`'s tests.
