---
title: Cut the planner's mistakes, the biggest source of lessons and extra rounds
type: research
status: resolved
assignee:
blocked_by: []
---

## Question

Most of the open `factory-learning` issues are `plan_gap`, not coder or style problems: the planner bundled a dependency update and a flag retirement into one change set, called a change to a user-facing API endpoint `internal_only` because it was described as tooling, and similar. Each one costs a run, a lesson and often a fix request. What would make the plan right more often: prompt changes, a stricter check in `orchestrator/planner.py` (it already rejects uncovered requirements, cycles, missing criteria and a missing flag), worked examples in the golden Intakes, or a different planner model? And how do we measure it, given the planner has no benchmark of its own?

## Added context

- Evidence: lessons such as #90 (an endpoint change misclassified as internal, which failed the first test pass), #107 and #104 (maintenance and a flag retirement planned together) and #52 (a misdiagnosis later corrected to a planning cause), and the fix requests filed as `prompt_gap` or `plan_gap`. Re-read the open `factory-learning` issues for the current list.
- The planner runs `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo`; `docs/benchmark-protocol.md` says planner, pipeline and retrospective have no component benchmark yet and go straight to the whole-run suite. A planner-only fixture set (Intakes with an expected change-set shape) would be cheap and could be run on every prompt change.
- Related: ticket 06 (triage and golden Intakes, `docs/golden-intakes.md`), the retrospective's plan_gap fixes that were closed or rejected, and the payoff metric (ticket 19), which would show plan_gap lessons per run.

## Resolution (2026-10-14)

Researched and built the offline part; decided with defaults, not put to the owner.

**Findings.** Re-read the open `factory-learning` issues. Most `plan_gap` evidence is older than the rules that now answer it: the planner prompt already says a flag retirement is internal with `flag: null` (#71, #69), forbids turning a production count into a criterion (#87) and defaults to one change set; `validate_plan` already rejects a new flag on a retirement. What was still open were two classes: an endpoint change described as tooling and marked internal (#90), and a dependency update planned together with a flag retirement (#106, #107). The planner also has no measurement of its own, so a fix could not be shown to work.

**Built.**
- Two checks in `orchestrator/planner.py` (`validate_plan`): a change set that is `internal_only` with no flag but whose criteria name an HTTP route, endpoint, screen, button or page is rejected (a flag retirement is exempt, because its criteria legitimately name the route it keeps live); and a change set that bundles a dependency update with retiring a flag is rejected. A rejected plan goes back to the planner with the reasons, as for any other plan problem.
- Two sentences in `agents/prompts/planner.md` saying the same.
- `agents/planner-fixtures/cases.json`: plans shaped like the real mistakes and their correct versions, run by `test_planner.py`, so the checker is proved against the recorded failures and each new `plan_gap` lesson becomes a case.

**Decided.** No model change (no evidence the model is the cause, and nothing to measure a swap with). No worked examples added to the golden Intakes yet (they are for requesters, not the planner). Not built: running the fixtures' *requests* through the live planner, which needs a repository checkout for the Agent to read; that is ticket 30. Measure effect with ticket 19 (plan_gap lessons per run).

Unit-tested. Not run live.
