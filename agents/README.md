# Agent configuration

The editable configuration for the Orchestrator's Agents, kept apart from the architecture and Standards so it can be tuned over time without touching them. Roles and stage order are defined in [ARCHITECTURE.md](../ARCHITECTURE.md#agents-and-build-run-stages); this directory holds only what is expected to change.

- [profiles.yml](profiles.yml): which model, endpoint, and prompt each role uses, plus the run limits (review rounds, default and maximum cost cap, credential lifetime). Switching a role's model or the provider is an edit here and nowhere else.
- `prompts/<role>.md`: one role prompt per Agent (`coder`, `reviewer`, `tester`, `pipeline`, `retrospective`), each edited independently.

The Build Run workflow reads these files from ai-factory at run time. They are never copied into a Managed App repo, so the coder can't edit its reviewer's instructions, and changes apply to the next Build Run without touching any Managed App.

A model is only eligible for a role if DeepInfra (or whichever provider is configured) serves it on an OpenAI-compatible API and returns per-response `usage.estimated_cost`, because the cost guardrail depends on that field. Smoke-test a new model against it before pinning.

## Prompt placeholders

The Build Run replaces `{{name}}` placeholders before invoking OpenHands.

| Role | Placeholders |
|---|---|
| coder | `app_name`, `round`, `task`, `findings_path` |
| reviewer | `app_name`, `base_sha`, `head_sha`, `verdict_path` |
| tester | `app_name`, `app_url`, `head_sha`, `report_path`, `previous_report`; env `PREVIEW_TOKEN` |
| pipeline | `app_name`, `head_sha`, `failure_run_url`, `diagnosis_path`, `context_dir` |
| planner | `app_name`, `build_kind`, `task`, `plan_path` (first stage of a Build Run for an Update App Intake; `orchestrator/planner.py` checks its output) |
| retrospective | `facts_path`, `result_path`, `categories` (run by `orchestrator/retrospective.py`, not the Build Run) |

## Output contracts

Each non-coder role writes JSON the Orchestrator parses; the Orchestrator never trusts a role's own conclusion field over the evidence.

- **reviewer** (`verdict_path`): `analysis`, `findings[{severity: blocking|minor, summary, evidence, file, line, requirement, suggested_fix, repro}]` (the last five are best-effort; empty when not applicable), `verdict`, in that key order. The Orchestrator derives the verdict from the findings.
- **tester** (`report_path`): `passed`, `results[{flag, check, status, passed, evidence, repro, api}]` (`api` lists the ids of the `api-check` helper checks the result rests on; the helper's log outranks the report, see ARCHITECTURE: Tester) (`repro` is best-effort), `limitations[]`. `status` is `passed`, `failed`, `blocked` or `not_run`; only `passed` passes, and the Orchestrator derives the top-level `passed` from the statuses (the boolean alone still works for an older report). `limitations` lists what could not be tested or cleaned up, and is shown in the Summary. The Orchestrator keeps a per-round scoreboard of check states and open findings (`artifacts/progress.json`, and `scoreboard` in the Report).
- **planner** (`plan_path`): `requirements[{id, text}]`, `assumptions[]`, `open_questions[{id, text, blocking}]`, `change_sets[{id, title, requirements, depends_on, criteria, verification, flag, internal_only, out_of_scope}]`. `orchestrator/planner.py` rejects a plan with uncovered requirements, a dependency cycle, a change set without criteria or verification, an update change set without its own flag, or more than 8 change sets, and reports blocking questions as needing a person.
- **pipeline** (`diagnosis_path`): `category: code|workflow|infra|flaky`, `summary`, `fix_request` (string or null), `retry_recommended`.

`agents/benchmark/` and `docs/benchmark-protocol.md` hold the whole-run benchmark that decides a model swap (a role may also name a `fallback_model`). `agents/smoke/` holds fixtures that replay known-buggy diffs through the reviewer; rerun it after changing the reviewer prompt or model. `agents/smoke-tester/` does the same for the tester: it serves a small flagged feature locally (the Starter Template and a stub GrowthBook, never production), once correct and several times with one seeded bug, runs the real tester prompt against it and scores the report the way the Orchestrator reads it. `--validate` needs no model and proves each bug is observable; a real run costs about $0.05 to $0.20 per run, and results vary a lot from run to run, so use at least 5 trials per fixture before concluding anything.

## Unattended-run limits

`limits.stuck_rounds` ends a run early (`stuck`, a needs-human Issue) when that many rounds in a row leave exactly the same checks failing and the same findings open. `limits.watchdog_*` control the watch after a release: for `watchdog_minutes` the Orchestrator polls the app's health and counts error-level log lines, and on `watchdog_max_failures` failures in a row or `watchdog_max_errors` new error lines it switches off the flags that run released (never a flag that already existed) and ends the run as `watchdog_disabled`. Both are in `profiles.yml`; setting either to 0 turns it off.
