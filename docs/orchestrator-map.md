# Orchestrator map

Where the code lives, by domain. A domain is a plain Python folder under `orchestrator/` that holds one part of the [flow spec](flow-spec.md) (steps are cited as `STEP n.m`): its code, its tests and its entry points. Nothing is installed or versioned. The layout was decided in ticket 04 of `.wayfinder/intake-planning-redesign/`; the moves are made by the tickets named below, one domain at a time.

**Status.** Today `orchestrator/` is flat. The "Today" column lists the current files (checked 2026-10-19) and the "Target" column the folder they move to. `shared/`, `request/`, `maintenance/`, `monitoring/` and `flag_lifecycle/` exist as folders (tickets 05 to 08); `boundary_test.py` enforces the rules below.

## Domains

| Domain (folder) | Steps | Today | Target files and notes | Ticket |
|---|---|---|---|---|
| Request (`request/`) | 1.1 to 1.3 | Built (ticket 06): `intake_labels.py` (the intake and start labels), `read_form.py` (`form_section`, `app_name`, `read_request` with the cost-cap rule), `render_form.py` (`form_body`), `check_target_app.py` (`is_factory_repo`), `find_intakes.py` (`intakes_with`), `file_intake.py` (`file_update_app_intake`: label, file, start with the PAT; used by maintenance, template sync, production feedback and flag retirement). The forms stay YAML in `.github/ISSUE_TEMPLATE/` | | 06 |
| Planning (`planning/`) | 2.1 to 2.6 | Built (ticket 09, the pure parts; the planner still runs inside the Build Run until ticket 13): `validate_plan.py` (the plan gate: size S or M, at most 6 criteria, `kind: staging` first for a new app, dependencies declared), `triage.py` (secret scan and feasibility), `render_child.py` (a change set's task text, the child body, `one_line`), `plan_comment.py`, `secrets_marker.py`, `file_children.py` (sub-issues, blockers, idempotent, all or nothing). *Still in `build_run.py`:* `plan_change`, `require_secrets`, `post_plan` | `plan_run.py`, `plan.yml` | 09, 13 |
| Staging (`staging/`) | 3.1, 3.2 | `infra/app-staging/*.sh`, `app-staging.yml` | the Python side (checklist, concurrency count); shell stays in `infra/` | 14 |
| Build Run (`build_run/`) | 4.1 to 4.14 | `build_run.py`, `api_check.py`, `ui_check.py`, `update_intake.start` | `start_build.py`, `read_child.py`, `prepare_run.py`, `run.py`, `write_code.py`, `review_code.py`, `ship_code.py`, `test_deployed_app.py`, `track_progress.py`, `gate_release.py`, `rollback_deploy.py` | 11, 12 |
| Flag Lifecycle (`flag_lifecycle/`) | 5.1 to 5.7 | Built (ticket 08, moved without changing behaviour): `flag_manifest.py` (manifest slugs, GrowthBook key), `flag_slug.py` (`issue-<n>`, `ensure_feature`), `flag_usage.py` (does the code read a flag), `missing_flag.py` (a flag missing at release), `story_link.py` (flag label, title tag, description, `link`), `release_features.py` (switch on the story's flag; never creates), `watchdog.py` (trip rules, `watch`, `disable_flags`), `retirement_selection.py` (which flags ride along), `retirement_check.py` (the verifier), `retirement_archive.py`, `dark_feature.py` (dark-broken, approve removal rules), `approve_retire.py` (the `approve-retire` workflow), `set_flag.py` (the by-hand switch), `fake_growthbook.py` (test support) | `issue-<n>` and `ensure_feature` built (08b); Starter flag-off/on test check (08c, `templates/starter/scripts/check-flags.mjs`) | 08 |
| Retrospective (`retrospective/`) | 6.1 to 6.6 | `retrospective.py`, `appstate.py`, `finalize`, `finish_update_intake`, `update_intake.advance` | lessons, minors and improvements, Agent and learning PR, story report, finalize, advance, parent closes | 10 |
| Try Fix (`try_fix/`) | 7.1 to 7.5 | `fixrequest.py` | route, requirements, fix child, resume, factory fix request, needs-human | 15 |
| Bugs (`bugs/`) | 8.1 to 8.4 | `production_feedback.py` | scan, dark versus released routing, regression issue | 16 |
| Maintenance (`maintenance/`) | none | Built (ticket 07): `template_sync.py`, `dependency_updates.py` (was `maintenance.py`); run as `python -m maintenance.template_sync` and `python -m maintenance.dependency_updates` | the two scheduled sources of Update App Intakes | 07 |
| Monitoring (`monitoring/`) | none | Built (ticket 07): `benchmark.py`, `canary.py`, `dashboard.py`, `fly_audit.py`; run as `python -m monitoring.<name>`. `audit.py` stays flat for now: `finalize` calls it, so it moves with `finalize` into Retrospective (ticket 10) | measurement and checks that serve no step | 07 |

## Shared (`shared/`)

What two or more domains use, each a small interface with its own tests. It imports no domain.

| File | Is | Ticket |
|---|---|---|
| `github.py` | `run`, `ensure_label` and `git_auth_env`: the one place that runs `gh`, taking the token per call (the PAT versus Actions-token choice). Built; `update_intake` and `fixrequest` use it, the other copies move with their domains | 05 |
| `outcomes.py` | the one list of Build Run endings and which are good, answered or failed. Built | 05 |
| `config.py` | the `profiles.yml` and limits loader, `FACTORY_DIR`, `GROWTHBOOK_API`. Built | 05 |
| `run_stops.py` | `BudgetExhausted`, `ProviderBlocked`, `NeedsHuman`: the ways a run stops that are neither a good ending nor a crash. Built | 05b |
| `http_client.py` | `request`: one JSON-over-HTTP call that never raises on a network error. Built | 05b |
| `provider.py` | the model provider: its address, how an empty-account refusal looks, `provider_check`, `model_status`. Built | 05b |
| `spend_budget.py` | `Budget`: the run's one cap, metered by scoped credentials. Built | 05b |
| `agent_runner.py` | `AgentRunner.run` (one Agent invocation: credential, environment, stall watch, spend and usage read back) and `json_output` (the file an Agent writes, with one retry). Built; the planner and the Build Run use it, the retrospective Agent moves onto it in its own ticket | 05b |
| `agent_process.py` | running an Agent as a process: as the Agent account, the isolation self-check, the stall watch, the kill by process group. Built | 05b |
| `agent_usage.py`, `agent_output.py`, `console.py` | the Agent's context numbers; the JSON file it writes (find it, explain what is wrong); the workflow log line. Built | 05b |
| `shell.py`, `starter_template.py`, `preview_token.py`, `app_state_record.py`, `api_check.py` | `sh` (run a command, fail loudly); the Starter Template files an Agent may not change and the ones the Orchestrator copies in; the Preview Token derivation (INV-08); the App State record's format plus the list of Managed Apps; the HTTP check helper the tester calls and the benchmark scores with. Built | 07 |
| `child_tickets.py` | a `ChildTickets` object for one parent: the `factory-plan` marker, file a child, add a blocker, readiness, parent lookup. Planned | 09 |

## Rules

- **Imports** (checked by `boundary_test.py`): `shared` imports no domain; every domain may import `shared`; `planning`, `build_run`, `maintenance`, `bugs`, `flag_lifecycle` and `try_fix` may import `request`; `build_run` may import `flag_lifecycle`; `retrospective` may import `try_fix`; `try_fix` may import `planning`; `monitoring` imports only `request` (benchmark files issues in the form's shape, fly audit checks the factory marker); no cycles. Anything else is a deliberate edit to the test and this page.
- **Talking through GitHub.** Domains mostly run as separate workflows, so they communicate through the `factory-plan` marker, labels, native dependencies and the App State record, not through Python calls.
- **Entry points.** A workflow sets `PYTHONPATH=orchestrator` and runs `python -m <domain>.<command>`. A command file is named for the command.
- **Tests** sit beside the code, named for the behaviour they check (`name_test.py`), and run per domain (`python -m unittest discover -s orchestrator/planning -t orchestrator`) or all together. `invariants_test`, `style_test`, `flow_spec_test` and `boundary_test` stay at the top of `orchestrator/`.
- **Moves.** A move is its own commit with behaviour unchanged. No re-export shim or old path is left behind; the workflow's command changes in the same commit.

## Imports that cross domains today

These are the couplings the domain tickets remove or put behind a named function:

- `build_run` imports `planning` (until ticket 13), `update_intake`, `fixrequest`, `appstate` and `audit`, so Planning, Retrospective and Try Fix all run inside Build Run; Flag Lifecycle is now called through its own files.
- `fixrequest` imports `update_intake`; `retrospective` imports `build_run` and `fixrequest`.
- `production_feedback` imports `build_run` for helpers and `fixrequest` to file issues. `maintenance/` and `monitoring/` no longer import any flat module.

## Workflows by trigger

- **An issue label:** `update-app-intake.yml`, `app-staging.yml`, `approve-retire.yml`, `factory-run.yml`. *Planned:* `plan.yml` on the two intake labels.
- **Manual (`workflow_dispatch`):** `build-run.yml`, `benchmark.yml`, `flag-set.yml`, `reviewer-replay.yml`, `smoke-reviewer-model.yml`, `teardown.yml`, `verify-secrets.yml`, `isolation-probe.yml`.
- **Scheduled (and manual):** `canary.yml`, `dashboard.yml`, `fly-audit.yml`, `maintenance.yml`, `production-feedback.yml`, `template-sync.yml`.
- **Pull request:** `factory-checks.yml`.

Today there are 19 workflows; `plan.yml` makes 20.

## The child ticket contract (`shared/child_tickets.py`)

A child ticket is a sub-issue of the Intake it was planned from. Planning writes it; the Build Run, the Retrospective and Try Fix read it. The sub-issue shape lives only in `ChildTickets` (create then add by numeric id, blockers, readiness, parent lookup with its 404).

The hidden `<!-- factory-plan:{...} -->` marker at the top of the body holds: `parent` (the Intake's number), `cs` (the change set id), `kind` (`staging` or `update`), `flag` (yes or no; the slug is always `issue-<n>`), `flag_story` (only on a fix child: the failed story whose flag it reuses), `internal_only`, `size` (`S` or `M`), `requirements`, `secrets` (names and purposes, never values) and, for now, `depends_on`. **Decision (ticket 09):** the native GitHub blockers are the source of truth for order, because the UI shows them and readiness is judged from each blocker's state; the marker's `depends_on` is a temporary copy of issue numbers for the label-based `update_intake.advance`, and the Retrospective ticket (10) removes it when it advances by blockers. The body below the marker is the Update App Intake form with the complete instructions (acceptance criteria, how each is checked, out of scope, the flag sentence), so a child needs nothing else to be built.

Filing is all or nothing and idempotent: a parent that already has children is left alone; if any call fails, the children made are removed from the parent and closed, and the error is raised, so the Intake can be planned again with no orphan. A child's parent is looked up with `parent_of` (None for an issue with no parent, which the Build Run refuses as unplanned).
