# Orchestrator map

Where the code lives, by domain. A domain is a plain Python folder under `orchestrator/` that holds one part of the [flow spec](flow-spec.md) (steps are cited as `STEP n.m`): its code, its tests and its entry points. Nothing is installed or versioned. The layout was decided in ticket 04 of `.wayfinder/intake-planning-redesign/`; the moves are made by the tickets named below, one domain at a time.

**Status.** Today `orchestrator/` is flat. The "Today" column lists the current files (checked 2026-10-19) and the "Target" column the folder they move to. Only `shared/` exists as a folder (`outcomes`, `config`, `github`, ticket 05); `boundary_test.py` enforces the rules below.

## Domains

| Domain (folder) | Steps | Today | Target files and notes | Ticket |
|---|---|---|---|---|
| Request (`request/`) | 1.1 to 1.3 | `form_section`, `app_name`, `is_factory_repo` in `update_intake.py`; `parse_intake` in `build_run.py`; the `file_*` of the detectors | `read_form.py`, `check_target_app.py`, `file_intake.py`; the forms stay YAML in `.github/ISSUE_TEMPLATE/` | 06 |
| Planning (`planning/`) | 2.1 to 2.6 | `planner.py`, `triage.py`, plan and child parts of `update_intake.py`, `plan_change`, `require_secrets`, `post_plan` in `build_run.py` | plan gate, refusal checks, child bodies, `plan_run.py`, `plan.yml` | 09, 13 |
| Staging (`staging/`) | 3.1, 3.2 | `infra/app-staging/*.sh`, `app-staging.yml` | the Python side (checklist, concurrency count); shell stays in `infra/` | 14 |
| Build Run (`build_run/`) | 4.1 to 4.14 | `build_run.py`, `api_check.py`, `ui_check.py`, `update_intake.start` | `start_build.py`, `read_child.py`, `prepare_run.py`, `run.py`, `write_code.py`, `review_code.py`, `ship_code.py`, `test_deployed_app.py`, `track_progress.py`, `gate_release.py`, `rollback_deploy.py` | 11, 12 |
| Flag Lifecycle (`flag_lifecycle/`) | 5.1 to 5.7 | `flag_retirement.py`, `flag_set.py`, flag helpers, `release`, watchdog in `build_run.py` | slug, create, release, retire, verify, watchdog; new `ensure_feature` | 08 |
| Retrospective (`retrospective/`) | 6.1 to 6.6 | `retrospective.py`, `appstate.py`, `finalize`, `finish_update_intake`, `update_intake.advance` | lessons, minors and improvements, Agent and learning PR, story report, finalize, advance, parent closes | 10 |
| Try Fix (`try_fix/`) | 7.1 to 7.5 | `fixrequest.py` | route, requirements, fix child, resume, factory fix request, needs-human | 15 |
| Bugs (`bugs/`) | 8.1 to 8.4 | `production_feedback.py` | scan, dark versus released routing, regression issue | 16 |
| Maintenance (`maintenance/`) | none | `template_sync.py`, `maintenance.py` | the two scheduled sources of Update App Intakes | 07 |
| Monitoring (`monitoring/`) | none | `audit.py`, `benchmark.py`, `canary.py`, `dashboard.py`, `fly_audit.py` | measurement and checks that serve no step | 07 |

## Shared (`shared/`)

What two or more domains use, each a small interface with its own tests. It imports no domain.

| File | Is | Ticket |
|---|---|---|
| `github.py` | `run` and `ensure_label`: the one place that runs `gh`, taking the token per call (the PAT versus Actions-token choice). Built; `update_intake` and `fixrequest` use it, the other copies move with their domains | 05 |
| `outcomes.py` | the one list of Build Run endings and which are good, answered or failed. Built | 05 |
| `config.py` | the `profiles.yml` and limits loader. Built | 05 |
| `run_stops.py` | `BudgetExhausted`, `ProviderBlocked`, `NeedsHuman`: the ways a run stops that are neither a good ending nor a crash. Built | 05b |
| `http_client.py` | `request`: one JSON-over-HTTP call that never raises on a network error. Built | 05b |
| `provider.py` | the model provider: its address, how an empty-account refusal looks, `provider_check`, `model_status`. Built | 05b |
| `spend_budget.py` | `Budget`: the run's one cap, metered by scoped credentials. Built | 05b |
| `agent_runner.py` | `AgentRunner.run` (one Agent invocation: credential, environment, stall watch, spend and usage read back) and `json_output` (the file an Agent writes, with one retry). Built; the planner and the Build Run use it, the retrospective Agent moves onto it in its own ticket | 05b |
| `agent_process.py` | running an Agent as a process: as the Agent account, the isolation self-check, the stall watch, the kill by process group. Built | 05b |
| `agent_usage.py`, `agent_output.py`, `console.py` | the Agent's context numbers; the JSON file it writes (find it, explain what is wrong); the workflow log line. Built | 05b |
| `child_tickets.py` | a `ChildTickets` object for one parent: the `factory-plan` marker, file a child, add a blocker, readiness, parent lookup. Planned | 09 |

## Rules

- **Imports** (checked by `boundary_test.py`): `shared` imports no domain; every domain may import `shared`; `planning`, `build_run`, `maintenance`, `bugs`, `flag_lifecycle` and `try_fix` may import `request`; `build_run` may import `flag_lifecycle`; `retrospective` may import `try_fix`; `try_fix` may import `planning`; `monitoring` imports no domain; no cycles. Anything else is a deliberate edit to the test and this page.
- **Talking through GitHub.** Domains mostly run as separate workflows, so they communicate through the `factory-plan` marker, labels, native dependencies and the App State record, not through Python calls.
- **Entry points.** A workflow sets `PYTHONPATH=orchestrator` and runs `python -m <domain>.<command>`. A command file is named for the command.
- **Tests** sit beside the code, named for the behaviour they check (`name_test.py`), and run per domain (`python -m unittest discover -s orchestrator/planning -t orchestrator`) or all together. `invariants_test`, `style_test`, `flow_spec_test` and `boundary_test` stay at the top of `orchestrator/`.
- **Moves.** A move is its own commit with behaviour unchanged. No re-export shim or old path is left behind; the workflow's command changes in the same commit.

## Imports that cross domains today

These are the couplings the domain tickets remove or put behind a named function:

- `build_run` imports `planner`, `triage`, `update_intake`, `fixrequest`, `flag_retirement`, `appstate` and `audit`, so Planning, Flag Lifecycle, Retrospective and Try Fix all run inside Build Run.
- `flag_retirement` and `build_run` import each other (one of the two imports is inside a function).
- `fixrequest` imports `update_intake`; `retrospective` imports `build_run` and `fixrequest`.
- `production_feedback`, `maintenance`, `template_sync` and `fly_audit` import `build_run` for helpers and `update_intake` or `fixrequest` to file their issues.
- `benchmark` and `canary` import `build_run` and `update_intake`; `flag_set` imports `build_run`.

## Workflows by trigger

- **An issue label:** `update-app-intake.yml`, `app-staging.yml`, `approve-retire.yml`, `factory-run.yml`. *Planned:* `plan.yml` on the two intake labels.
- **Manual (`workflow_dispatch`):** `build-run.yml`, `benchmark.yml`, `flag-set.yml`, `reviewer-replay.yml`, `smoke-reviewer-model.yml`, `teardown.yml`, `verify-secrets.yml`, `isolation-probe.yml`.
- **Scheduled (and manual):** `canary.yml`, `dashboard.yml`, `fly-audit.yml`, `maintenance.yml`, `production-feedback.yml`, `template-sync.yml`.
- **Pull request:** `factory-checks.yml`.

Today there are 19 workflows; `plan.yml` makes 20.
