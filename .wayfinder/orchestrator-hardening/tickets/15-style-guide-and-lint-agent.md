---
title: A style guide and linting agent (future)
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

Saved now, to be done later. Should the Factory have a dedicated agent that owns the **style guide and the lint rules** of the Starter Template (and so of every Managed App), so that style, naming and mechanical-quality findings are prevented by checks at creation time instead of being found by the reviewer? What does it own, when does it run, and how do its changes reach the apps?

Decide:

(a) **Scope.** The written style guide (`STANDARDS-CODING.md` today says style is purely mechanical and an auto-formatter is the whole guide), the Starter's lint and formatter config (`eslint.config.mjs`, `.prettierrc.json`, the `check` and `audit` scripts), TypeScript strictness, and template defaults. Not application logic.

(b) **Input.** Recurring review findings and lessons (ticket 14 decides which findings are "preventable by a check"), coder first-pass test failures, and findings the tester or post-mortem names as a missing template default. Pull from the `factory-learning` issues and the dashboard history rather than from a single run.

(c) **Output and merge policy.** A proposed change to lint config, a custom rule, a template default or a prompt line, each with a regression fixture, delivered the way learning pull requests are today (`orchestrator/postmortem.py`, the Factory Run) and auto-merged only when additive (the existing rule: additive lint or formatter changes to the Starter Template with all checks green, INV-15). Decide whether this is a new role with its own prompt, model and cost cap, or the existing post-mortem Agent with a narrower brief and the fix-type ladder.

(d) **Propagation.** Template sync (`orchestrator/template_sync.py`) already carries Starter changes to existing apps through an Update Intake; a tightened rule may fail existing code, so decide how an app adopts a stricter rule (fix-forward in the same sync run, or ratchet: new rules start as warnings).

(e) **Guardrails.** Rules must not make the coder fight the linter for rounds (the stuck detector already stops a run that repeats the same failures), must be fast (`npm run check` is about 2.5 seconds today and stays on the per-round path), and must not loosen a check.

(f) **Measure.** Review findings per run and rounds per run before and after, using the same data as ticket 14.

## Added context

- Why it is a ticket and not built: ticket 14 first has to decide which findings count as preventable and how repeated ones become Factory tickets. This agent is the consumer of that decision.
- Existing pieces to reuse: the learning loop's fix-type ladder and guardrails (lesson fixtures, required checks, recurrence tracking, revert on "fix ineffective"), the Factory Run workflow, the auto-merge policy, and the Starter's `lint`, `format` and `check` scripts (ticket 09).
- The owner's stated direction: style guide and linting should be the primary tool for review findings, with a dedicated agent for it in future.

## Resolution (2026-10-14)

Decided, and the first slice built and unit-tested (not run on a real app). Where the owner's words left a choice, the reading used is stated.

**What the data showed first.** The open `factory-learning` issues are not about formatting or naming. They are mostly `plan_gap` (the planner split or classified a change wrongly) and flag-state patterns the Starter did not make easy, and the minor findings are test quality (a test that asserts on `App.tsx` source text, #104; a test that only asserts a `flags.json` entry exists, #57). So the useful scope is the Starter's mechanical checks, mainly test-quality and flag-usage rules, not a style guide. The biggest lever on rounds is still the planner, which this ticket does not cover.

(a) **Scope.** The Starter's mechanical checks: the ESLint rules, the Prettier config and the `check` script, plus template defaults. The written style guide stays short and says checks, not prose (`STANDARDS-CODING.md`, Style). Not application logic. `tsconfig` is not made Orchestrator-owned: apps legitimately edit its `include` and `paths`, so protecting it would block real changes.

(b) **Input.** The same lessons and minor findings the retrospective already files (so the findings in the categories ticket 14 made structural: `test_quality`, `style`, `duplication`, `flag_misuse`), plus first-test-failure lessons with a `template_gap` cause. Recurrence counting is not built, so the first occurrence is acted on, as the learning loop does today, with the duplicate check stopping a reworded repeat.

(c) **Output, and who.** **No new role** (owner's choice): the retrospective Agent with a lint-first brief. For a finding a lint rule can catch it adds a precise `no-restricted-syntax` entry to `templates/starter/eslint.config.mjs` (additive, so it auto-merges under INV-15) and a failing and a passing case to `agents/lint-fixtures/cases.json`, which `orchestrator/test_starter_lint.py` runs with the real ESLint in the PR checks. It never edits an app's code.

(d) **Propagation.** Owner's direction: only the coder fixes what the style guide and template report; the sync job creates the work for each Managed App; the Update Intake picks it up, plans it and releases it by the same process as everything else. Template sync already files one Update Intake per behind app and starts it, so that Intake is the work item, and the change is that the lint and formatter config is now copied in by the Orchestrator at the start of it (`stage_template_config`), committed locally after the run's base and pushed only with the coder's first reviewed work, so a stricter rule never puts a red Test Gate on `main` by itself and the coder fixes the violations in the same run. *Reading used:* I did not add a second issue in each app's own repo before the Intake; if you want that record in the app's backlog, say so and it is a small addition to `template_sync.py`. A ratchet (rules start as warnings) was offered and not chosen; the stuck detector and the round limit bound a sync run that cannot clear the violations, and then the dark-feature and retry path applies.

(e) **Guardrails.** `eslint.config.mjs`, `.prettierrc.json` and `.prettierignore` are protected and Orchestrator-owned (INV-02, INV-47), so the coder cannot loosen a rule; the coder prompt says to fix the code and not to add `eslint-disable`, `@ts-ignore` or `@ts-nocheck`, and the Orchestrator names any such suppression a diff adds as a minor finding (`suppression_findings`), where the retrospective sees it. The config stays additive; the four starting selectors are precise, and `npm run check` is unchanged in speed.

(f) **Measure.** Not built: review findings per run and rounds per run before and after, from the same data as ticket 14, needs the dashboard to collect more runs and the payoff metric.

**First slice built:** four lint selectors in the Starter (no reading application files in a test, by call or by method, no asserting on `flags.json`, no committed `.only`; in test files only), ten cases, the protected and held lint config, the suppression finding, the retrospective and coder prompt changes, INV-47. **Not built:** the optional app-repo issue, recurrence counting, the measure, a rule for weak assertions such as a test with no assertion at all (it needs a plugin dependency, which is a cost to weigh).
