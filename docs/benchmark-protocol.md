# Benchmark protocol: switching models and prompts safely

The Factory is meant to swap its models out as better ones appear: cheaper, faster, more specialised. A swap is only safe if it is measured on the real
thing. This protocol says what to run, when, and what counts as good enough. It follows the practice called **evals**
([Anthropic's guide](https://anthropic.com/engineering/demystifying-evals-for-ai-agents)): a fixed set of tasks, each with a grader that decides pass or fail
from the final outcome by code, run on every change and compared with a baseline.

## Words

| Term | Here |
|---|---|
| **Task** | One Intake with a known expected outcome (`agents/benchmark/suite.json`) |
| **Suite** | The 7 tasks: a flagged route, an edge-case validation, an internal refactor, a named flag retirement, an ambiguous spec, and two refusals (payments, a pasted secret) |
| **Oracle** | The checks that decide a task: `api_check` scenarios against the deployed bench app, plus the outcome the task expects and any cost limit. Code decides, never a model. |
| **Baseline** | The last accepted pass (`agents/benchmark/baseline.json`) |
| **Rules** | What counts as good enough (`agents/benchmark/rules.json`) |
| **Candidate** | A pass whose `agents/profiles.yml` names the new model(s) |

## When to run what

| Change | Run | Spend |
|---|---|---|
| Any change to a prompt or a role's model | Unit tests and the reviewer smoke fixtures (CI, automatic) | cents |
| A new model for one role | The role's component benchmark (below), then the whole-run suite | $0.2 to $2, then $0.8 to $3.7 |
| A prompt or planner/validator change that alters behaviour | The whole-run suite | $0.8 to $3.7 |
| Nothing pending | Nothing. The nightly model canary runs on its own. | about a cent |

The whole-run suite takes **1.8 to 3.5 hours** and **about $0.80 to $3.70** (five tasks, each planned at $0.04 to $0.10 and then a Build Run at $0.1 to $0.6, plus two refusals that end at planning;
`benchmark.py plan` prints the estimate). Do not run it on a schedule: run it when a swap is actually pending.

## Evaluating a candidate model, step by step

1. **Component benchmark for the role** (cheap, catches a bad model early). Models come from `MODELS=<a,b>` (the first is the baseline):
   - coder: `MODELS=<current>,<new> python3 agents/smoke-coder/run.py` and `agents/replay/coder_replay.py`
   - reviewer: `agents/smoke/run.py` (the seeded-bug fixtures; CI runs it when a prompt or the profile changes)
   - tester: `agents/smoke-tester/run.py` (seeded-bug notes API; about $1.8 a pass at 2 trials)
   - planner, pipeline, retrospective: no component benchmark yet; go straight to the whole-run suite.
2. **Dry run the whole-run pass:** Actions, "Benchmark", leave `execute` off, `candidate` = `coder=<new-model-id>` (any `role=model` pairs, comma separated). It prints
   the plan and the estimate and spends nothing. Locally: `PYTHONPATH=orchestrator python3 -m monitoring.benchmark plan --candidate coder=<new-model-id>`.
3. **Run it:** the same workflow with `execute` on. The runner creates a branch with the candidate's `profiles.yml` (and the limits that keep passes comparable: no
   flag-retirement ride-along, a 2-minute watchdog, no daily cap), then for each task resets the bench app to its frozen commit, files the task as an Update App Intake labelled `benchmark`, dispatches the real
   `plan.yml` from that branch (so the planner measured is the candidate's), then dispatches the real `build-run.yml` from that branch for each child the plan filed, in order,
   stopping at the first child that does not release. A task that ends at planning (a refusal, a question, a missing secret on an existing app) is scored on that ending. The `benchmark` label is
   inherited by the children, which keeps the production workflows from starting them with the production models. The runner reads the Report (cost, rounds and time of the
   planner and every Build Run added up, the planner's cost from the spend ledger) and runs the oracle. It deletes the branch and archives the bench flags at the end.
4. **Read the result** (the step summary and the `benchmark-result` artifact): passes, cost, rounds and minutes per task, and a verdict against the baseline.
5. **Accept or reject.** The rules (`rules.json`) accept a candidate when:
   - it passes no more than `max_pass_drop` (1) fewer tasks than the baseline,
   - every task tagged `refusal` or `safety` that passed in the baseline still passes,
   - its cost is at most `max_cost_ratio` (1.3) times the baseline's,
   - its mean review rounds rise by at most `max_rounds_delta` (0.5).

   A candidate that is accepted **and** costs or takes at most `improvement_ratio` (0.9) of the baseline is reported as an **improvement**: that is the swap to make.
6. **Make the swap:** change `model:` in `agents/profiles.yml` (keep the old one as `fallback_model` if it is still served), `benchmark.py accept benchmark-result-<label>.json`,
   and commit the new `baseline.json` with the profile change. If a borderline result matters, run it again: a single pass is one trial per task and Build Runs vary.

## What it does not cover (yet)

A new app's plan and staging (they need a fresh app each time), UI changes (the tester's `ui-check` has its own tests), plans of several change sets (the tasks are one
slice each; the runner can run more than one child, but no task asks for it), failures and their fixes (Try Fix), and the retrospective Agent. Add a task to `suite.json` when a real failure shows a gap: start from real failures, with an expected outcome and an oracle, and include cases
that should be refused as well as built, so a cheaper model cannot win by being careless.

## Fallback and the nightly canary

Each role in `agents/profiles.yml` may name a `fallback_model`. Before any work, a Build Run asks the provider for one token from each model it will use
(`BuildRun.check_models`). A model the provider no longer serves is replaced by its fallback for that run (recorded as `fallbacks` in the Report); if there is no
usable fallback the run stops at once with the reason instead of failing after a checkout and a planner call. A zero balance is still `provider_blocked`.
Every night the **model canary** (`canary.yml`, `orchestrator/monitoring/canary.py`) asks the same question of every configured model, primaries and fallbacks, and keeps one
`model-drift` issue open while any is missing, so a retirement is found before an unattended run meets it. Choose the replacement with the steps above.

## Setting up the bench app (once)

See `agents/benchmark/bench-app-spec.md`. The first baseline pass is a pass with no candidate.
