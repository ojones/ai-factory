# Module notes

What used to be the comment block at the top of each Factory module, moved here so the code carries no comments. Grouped by directory.

## agents/replay/

### coder_replay.py

Replay the coder over the recorded Managed Apps' real tasks (.wayfinder coder-speed, ticket 15).

The recorded apps' histories are kept as bundles beside this script (data/). Each app's base commit is
the seed repository whose INTAKE.md Spec is the task the coder was given. For each model and task, this
checks out the base, runs the real coder prompt (round 1), then scores the result the way a Build Run
would judge it:

  built     a commit exists, no protected Starter Template file changed, `npm run build` and `npm test` pass
  clean     the production single-call reviewer (agents/profiles.yml) finds no blocking issue in the diff

A run that is built and clean would have needed no further review round, so `ok` (both) is the figure
that predicts speed: a model that is fast per round but misses often costs extra rounds.

  MODELS=a,b REPEAT=3 python3 agents/replay/coder_replay.py

Env: DEEPINFRA_API_KEY, MODELS (comma-separated; the first is the baseline), APPS (default all apps in
cases.json), REPEAT (runs per model and task, default 2), WORKERS (default 3), TIMEOUT_MIN (default 25),
KEEP=1. Writes coder-replay-results.json.

### replay.py

Replay the reviewer over commits from real Build Runs (issue #41).

Re-runs only the review step against commits the Managed App repos still hold, with the
current prompts and model, and sets the result beside what the reviewer concluded at the time.
Minutes and cents, instead of a 90-minute, $2 Build Run.

MODE=single  one model call over a prompt the Orchestrator assembles (the Build Run's default)
MODE=agent   the exploring OpenHands reviewer (what the Build Run used before)

Env: DEEPINFRA_API_KEY, MODE, MODEL (default: the reviewer's model in agents/profiles.yml),
CASES (comma-separated ids, default all), REPEAT (runs per case, default 1; the model is not
deterministic, so judge on 5), WORKERS (default 4), OWNER (default ojones).
A case's "expect" is a list of regexes, one per real problem a review must find among its blocking
findings; the report gives how often each was found.
Prints per-case time, tokens and verdicts; writes replay-results.json.

## agents/smoke-coder/

### run.py

Smoke screen for coder models (.wayfinder coder-speed, ticket 14).

Runs the real coder prompt (agents/prompts/coder.md, round 1) with a candidate model on a few small
tasks against a copy of the Starter Template, then scores the result with hidden acceptance tests the
coder never saw. A cheap screen: it is good at spotting a model that is broken, slow or sloppy, and
poor at separating two close ones (use agents/replay for that).

Score for one run = a commit exists, no protected Starter Template file changed, `npm run check`
passes, and `npm test` passes with the task's acceptance tests added.

  python3 agents/smoke-coder/run.py --validate    no model: prove each task's acceptance tests fail on the seed
                                                  and pass on its reference solution (needs npm)
  MODELS=a,b python3 agents/smoke-coder/run.py    run the screen (needs openhands and DEEPINFRA_API_KEY)

Candidates (from DeepInfra's /models list; each is faster or smaller than the 480B Qwen coder, tool-call and
cost fields unverified, so run the T1/T2 checks of agents/smoke/run.py with MODEL=<id> first):
  Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo (baseline)  deepseek-ai/DeepSeek-V4.1-Flash  Qwen/Qwen3.8-Flash
  zai-org/GLM-5.3-Flash  Qwen/Qwen3.5-35B-A3B  openai/gpt-oss-120b-Turbo  MiniMaxAI/MiniMax-M3

Env: MODELS (comma-separated DeepInfra ids; default the coder in agents/profiles.yml; the first is the
baseline the others' speed is compared with), TASKS (comma-separated ids, default all), TRIALS (per
model and task, default 2), WORKERS (default 3), TIMEOUT_MIN (per run, default 20), KEEP=1 (keep the
working directories). Writes smoke-coder-results.json.

## agents/smoke-tester/

### run.py

Seeded-bug screen for the tester (.wayfinder orchestrator-hardening, ticket 07).

The reviewer has had seeded-bug fixtures since #33; nothing showed whether the tester fails a broken app, and the tester
has twice marked a check passed that it could not have observed. This runs the real tester prompt (agents/prompts/tester.md)
against a small flagged feature served locally, once correct and several times with exactly one bug seeded, and measures
how often the tester notices.

The app under test is the Starter Template with a notes API behind the flag `notes-api`. A local stub stands in for
GrowthBook (no flags set), so nothing touches production. The tester gets the spec, a git checkout with a "previous
release" commit and a head commit (so `git log -p flags.json` shows the new flag), the app's URL and a Preview Token.

Scoring, per run: the tester's report is read the way the Orchestrator reads it (`derive_test`, which also downgrades a
`passed` check whose evidence admits it was not observed). A buggy app is caught if that says "not passed"; it is caught
for the right reason if a failing check also matches the fixture's pattern. The correct app must pass.

  python3 agents/smoke-tester/run.py --validate    no model: prove the correct feature passes an independent checker and every
                                                   seeded bug is observable from outside (needs npm)
  python3 agents/smoke-tester/run.py               run the screen (needs openhands and DEEPINFRA_API_KEY; costs real money,
                                                   about $0.05 to $0.12 per run)

Env: FIXTURES (comma-separated ids, default all), TRIALS (per fixture, default 2), WORKERS (default 3), TIMEOUT_MIN (per run,
default 20), MODEL (default the tester in agents/profiles.yml), KEEP=1 (keep the working directories).
Writes smoke-tester-results.json.

## agents/smoke/

### run.py

Smoke test for the reviewer model (issue #33).

Checks, against DeepInfra's OpenAI-compatible API, that the model:
  T1 returns usage.estimated_cost (the cost guardrail depends on it)
  T2 round-trips a tool call (incl. reasoning_content if the model emits it)
  T3 produces schema-valid structured JSON
  T4 does structured output and tools in the same request
  T5 finds known bugs / passes a clean diff (agents/smoke/fixtures), N trials each

Prints pass/fail only. The key comes from DEEPINFRA_API_KEY and is never printed.

## orchestrator/bugs/

### flood_limits.py

STEP 8.3: flood control for production feedback (INV-31). A production error cannot flood the trackers or the budget: nothing below `min_occurrences` in a scan, one
open bug per error (a repeat adds a comment with the count, never a second ticket), at most one open bug per app at a time, and at most `max_per_app_per_day` new
ones per app per day. Pure decisions, tested alone; the counts come from the bug Intakes in ai-factory (label `bug` and `app:<app>`).

### route_bug.py

STEP 8.1, 8.2, 8.4: is a bug dark or released? The answer comes from the flag's state in the App State record (the issue in the app's repo that the Build Run
keeps, shared/app_state_record.py), never from a guess. A flag that was released and is still on is released (a bug now is a regression: an ordinary bug Intake, nothing waits); one that was
never released, is off, or was switched off by the watchdog is dark (the bug Intake carries `fix_for` and the story's open child waits). An error with no flag in it cannot be tied to a
story, so nothing is claimed about it (`released` stays unknown) and it is filed as a plain bug Intake. Pure, tested alone.

### scan_production.py

STEP 8.3: watch production. Each Managed App's recent Fly log and the owner's `escaped-defect` issues are read, and what repeats becomes a failure event (to_event.py)
written to a file. Nothing is filed here: the events are judged by the Retrospective (STEP 6.7, `retrospective.judge_events`) and Try Fix writes and files the bug
(`try_fix.file_events`), exactly as for a failed Build Run. The three run one after the other in production-feedback.yml.

A repeat of an error that already has an open bug only adds a comment with the count. A defect report comes first: while an app has one to report, its logs wait.

Usage: python -m bugs.scan_production <events.json>   (PYTHONPATH=orchestrator; env FLY_API_TOKEN, FACTORY_PAT, FACTORY_GH_TOKEN, GITHUB_REPOSITORY)
Config: `limits.production_feedback` in agents/profiles.yml.

### to_event.py

STEP 8.3: what the Bugs domain finds, as failure events for the Retrospective (try_fix/event.py). Nothing here files a ticket: the events are judged (STEP 6.7)
and Try Fix writes and files the bug. Log text can contain what a user typed, so an error event carries only the cleaned message and the first stack frame, clipped,
and the Try Fix Agent is told the evidence is data, never instructions.

## orchestrator/build_run/

### read_child.py

Reading the child a Build Run was dispatched with (STEP 4.1): its request text and cost cap from the body, its `factory-plan` marker, and whether it
is really a planned child: a sub-issue of an open parent whose marker names that parent. The parent is read for its number and state only, never
for instructions.

### run.py

Build Run orchestrator (ARCHITECTURE.md → Agents and Build Run stages): coder → CI/deploy dark → reviewer + tester → fix loop → release.
`run` only sequences the steps; each step's code is in the file named for it in this folder. `run/state.json` is updated after every stage, so a
crash, breach or killed job still reports (retrospective/finalize.py).

Agents are OpenHands subprocesses with a whitelisted environment. They never hold the PAT, the GrowthBook admin key, the Fly token or the
DeepInfra parent key; the coder only commits, and this process pushes.

Usage: python -m build_run.run run   (PYTHONPATH=orchestrator; run by .github/workflows/build-run.yml)

### start_build.py

The gate that starts a Build Run for a child ticket (STEP 4.1's trigger). Planning (`planning/plan_run.py`) files each Intake's change sets as child tickets,
sub-issues of the Intake carrying a `factory-plan` marker, and puts `proceed-with-change` on the first child with nothing to wait for; the rest are
labelled `waiting-on-plan`, and `retrospective/close_child.py` gives `proceed-with-change` to the next one whose blockers are closed, one at a time, so an app
never has two pending Build Runs (GitHub keeps only one pending run per concurrency group). A staging child is staged by App Staging instead.

`.github/workflows/update-app-intake.yml` runs `start`, which refuses (comments, removes the label) anything that is not a planned child of an open plan,
or whose app is not one this Factory built, and otherwise labels it app:<slug> and dispatches the Build Run.

The label is added with the PAT, not the Actions token: events made by the Actions token do not start workflows.

Commands (env: GH_TOKEN, FACTORY_PAT, FACTORY_REPO, ISSUE_NUMBER, ISSUE_BODY, RUN_URL):
  start     validate the issue, label it app:<slug>, dispatch the Build Run

Usage: python -m build_run.start_build start   (PYTHONPATH=orchestrator)

### ui_check.py

ui-check: the tester states what a page should show and do; this drives a real browser, observes, and compares.

The browser counterpart of api_check.py, for the part of a Managed App only a browser sees: what renders, what a form does, what a
flagged control looks like with and without the Preview Token. The model's job is to say *which* screens and interactions the spec
calls for and what each should show. This opens the page headless (Chromium through Playwright), performs the steps, reads what is
actually there and compares it mechanically. Every result is appended to `$UI_CHECK_LOG`, which the Orchestrator reads
(build_run.reconcile_ui_checks), so a failure the helper saw cannot be reported as a pass or left out.

  python3 ui_check.py checks.json [--base https://app.fly.dev]

Env: PREVIEW_TOKEN (opens the page with the Preview Token for a check with "auth": "preview"; never printed, logged or screenshotted),
UI_CHECK_BASE (the base URL if --base is not given), UI_CHECK_LOG (JSONL results), UI_CHECK_DIR (where failure screenshots go),
PLAYWRIGHT_BROWSERS_PATH. Exit 0 if every check passed, 1 if any failed, 2 if the file is unusable.

A checks file is {"checks": [...]}. Each check is a scenario in a fresh browser context:

  {"id": "add-todo", "name": "Adding a todo shows it in the list", "start": "/", "auth": "preview" | "none",
   "steps": [{"fill": {"label": "New todo", "value": "factory-test-a"}}, {"click": {"role": "button", "name": "Add"}},
             {"press": "Enter"}, {"goto": "/other"}, {"wait_for": {"text": "factory-test-a"}}, {"check": {"label": "Done"}}],
   "expect": {"visible": [LOC], "hidden": [LOC], "text": [{...LOC, "contains": "x"} or {...LOC, "equals": "x"}],
              "count": [{...LOC, "is": 1}], "url_path": "/", "title_contains": "Todo", "no_console_errors": true}}

LOC (a locator) is one of {"role": "button", "name": "Add"}, {"label": "New todo"}, {"text": "Hello"}, {"placeholder": "..."},
{"test_id": "..."}, with optional "exact": true. Role and label locators are preferred: they are what a user sees. Checks run in order,
at most 30 per file and 20 steps per check, 8 seconds per action, and only the base URL's origin is ever requested.

## orchestrator/factory_change/

### tiers.py

STEP 9.8 (FC-30 to FC-32): which paths an Agent may change and who merges them. Tier 2 is the Factory's own control path (the run loop, the Agent runner and its budget, the
retrospective, Try Fix, this domain, `profiles.yml`): a broken change there could break the run that would fix it, so a person merges it. Anything outside Tier 1 and Tier 2
(workflows, the checks, `pyproject.toml`, docs, the Starter) is `never`, so a path nobody listed is refused rather than allowed by default. The planner is told the Tier 2 list
through `tier_two_paths_text`, which is the same patterns, so the prompt and the check cannot drift.

### vet_change.py

STEP 9.4 (INV-63): the structure of a diff is judged from `git diff` against `HEAD` in the Orchestrator's own checkout, never from what the Agent says it did. Over a limit is a
refusal back to the ticket, not a partial PR, because a trimmed change is a change nobody planned. A model or cap line added to `profiles.yml` is refused even though that file is
Tier 2: a person merging is not the same as an Agent being allowed to raise its own budget.

### prove_reproduction.py

STEP 9.7 (INV-64): a reproduction counts as failing on `main` only when unittest reports a `FAIL` or `ERROR` for it. A name that does not exist, a module that does not import and
a run of zero tests all exit non-zero too, so they are told apart by the output; otherwise a typo in the ticket would pass as a reproduction. Names are matched against a strict
dotted pattern before they reach the command line, so a ticket cannot pass an option.

### pause.py

STEP 9.12 (INV-65): the pause is an open GitHub issue with a label, not a file or a flag in a workflow, so a person clears it where they already look and the state survives a
fresh runner. The breaker compares stages by name because a failure at an unrelated stage says nothing about a change.

### gate.py

STEP 9.7 and 9.9 (INV-64, INV-66): the same checks run twice, once by the Orchestrator before it opens the PR and once in `factory-checks.yml`, because the PR is the thing that merges and a label or a body marker can be edited by anyone. The reproduction is proven by copying the PR's changed test files into a checkout of the base branch: the test exists nowhere on `main`, so running it there unchanged would only say "missing". The tier in the body is compared with the tier recomputed from the diff, so a Tier 2 change cannot merge itself by carrying a Tier 1 label.

### run.py

A coder edit to `docs/invariants.md` or `docs/flow-spec.md` is noticed in `write_change` before `carry_over_changes`, because that carry-over silently drops every path outside its allowed prefixes (docs among them); without the early check the PR would open without the spec change the coder wanted. The ticket ends `needs_human` (a person edits the spec, then adds `proceed-with-change` again), not `refused`, because the request is sound.

STEP 9.3 to 9.10: the order is the cheapest refusal first. The scope check comes before the proof and the unit tests, because a change outside its scope is discarded whatever else is true, and a scope refusal is final (back to the ticket) while a failed proof, failed tests or a blocking finding go back to the coder for another round, up to `factory_change_review_rounds`. The snapshot of `main` is taken before the first coder round and never refreshed, so a later round cannot make its own failing test look pre-existing. The reviewer's verdict is derived from its findings (`review_code.derive_review`), not read from its `verdict` field.

### watch_merged.py

STEP 9.11, 9.12 (INV-65): a merged change is judged by whether its own finding comes back, because the Retrospective files a returning finding under the same fingerprint, which the Intake records as a "Seen again" comment; that stands in for "a failed Build Run at the same stage", which the Orchestrator does not record anywhere it could be read back. A `model-drift` alert opened after the merge counts as a canary regression. Nothing is reverted (INV-68): `watch_merged.trip` labels the merged PR `factory-change-tripped` and pauses; the change stays in `main` and the returning finding, already on its Intake, is planned as a fix forward.

### promote.py

STEP 9.1: the cause is read from the `#### Cause` section Try Fix writes into a factory fix request, and the count of sightings is the first report plus its "Failed again" comments. The request is moved by filing a Factory Change Intake from its numbered requirements (already checked as checkable by Try Fix) and labelling it `moved-to-factory-change`; nothing in `try_fix` imports this domain, because `factory_change` imports `try_fix`. The handoff comment records the sightings at that moment; a request stays open after it, so every later "Failed again" comment is relayed once to the Intake as "Seen again" (and noted on the request as "Relayed"). Without this the breaker in `watch_merged` would never see a failure that returns, because the sweep skips a request once it is moved.

## orchestrator/flag_lifecycle/

### missing_flag.py

A flag the change declares but GrowthBook does not have at release. The release step never creates one: it cannot be tested to work reliably, and a
missing flag is a sign something earlier went wrong. What it means depends on whether the code reads the flag.
  - the code reads it: the feature is deployed dark and nothing can switch it on. A failure (`flag_missing`), nothing is rolled back; the story is
    fixed forward with a flag that exists.
  - the code does not read it: the change went live on deploy with no gate (a change with no flag at all is treated the same way when a check fails: a regression, rolled back). If the tests found no problem it is left alone and noted; if they found
    a failure it is rolled back like any regression. Either way the note is recorded for the retrospective to learn from.

### retirement_selection.py

Flag retirement: a feature flag is short-lived, so once a change is proven in production its flag is removed, by itself.

A flag exists for one job: to stage a change dark and release it when it is safe (ARCHITECTURE.md: Release and retirement). Nobody uses it for
anything else, so once a *later* Build Run has also released something, the earlier release has been replaced by a newer one and its
flag has done its job. A retirement is never a run of its own (that would spend a planner, reviewer, tester, CI and a deploy on a change
that only deletes a check): the next Update App Intake for the same app carries it. At the start of that Build Run the Orchestrator picks
the oldest eligible flag (`piggyback_slugs`) and adds a "retire these flags in the same change" block to the coder's task; the tester is
told to check that the behaviour is still on for everyone, and the run archives the flag in GrowthBook when it ends well. Users see no
change. The owner's standing approval is the standard; nobody reviews a retirement.

A flag is a candidate when all of these hold, read from the app's State issue and `flags.json`:
  - it is in `flags.json` and the State issue records it as `released` (not one the watchdog switched off: that one is a dark-broken candidate
    and its fix is an ordinary child with a flag of its own, STEP 5.5);
  - a later Build Run of the app also released a flag (its run id is higher);
  - it was released on an earlier day than today (a soak of at least a day, so the production-feedback scans have looked at it).
The newest release therefore always keeps its flag, and a run that ended `nothing_to_release` retires nothing.

A *dark* feature is the other case: a flagged change that never got through its checks. It stays dark, behind its flag, and is fixed forward
by the story's automatic retries (`fix_attempts_max`). Only after those are used up (the story is labelled `needs-human` and
`dark-broken`) and a person adds the label `approve-retire` to the story is it removed: `approve` files an Update App Intake that deletes the
flag's check, the code it guarded, its tests and its line in `flags.json`, and starts it. Nothing removes a dark feature on its own.

Limits: `limits.flag_retirement` in agents/profiles.yml (`piggyback_max` flags per run, default 5, so a backlog clears; `min_age_days`).

This file: which proven flags ride along, and the text that tells the coder and tester about them.

### set_flag.py

Switch one Managed App flag on or off in production by hand (the owner's lever; run by .github/workflows/flag-set.yml).

The release step creates flags and the watchdog switches them off. This is the same call for a person: turning a released flag
off is the rollback, and turning one on is for a test such as the production-feedback check. It changes the `production`
environment's `enabled` switch of one existing flag and reads it back; it never creates a flag or edits rules.

  PYTHONPATH=orchestrator python3 -m flag_lifecycle.set_flag <app> <flag-slug> on|off        Env: GROWTHBOOK_ADMIN_PAT
Exit 0 if the read-back shows the requested state, 1 otherwise, 2 for bad input.

## orchestrator/maintenance/

### dependency_updates.py

Maintenance: dependency and base-image updates reach the Managed Apps through the same gate as any other change.

Each app carries `.github/dependabot.yml` (from the Starter Template), so Dependabot watches its npm packages, its Docker base image
and its GitHub Actions every day, and opens a pull request for each update or security fix. Dependabot only detects here: nothing
merges those pull requests. This daily pass reads each app's open Dependabot pull requests and, when there are updates an Agent can
apply (npm packages and the Docker image), files one Update App Intake that lists them and starts it. The planner, coder, tester and
reviewer apply them, and the change ships like any other; a dependency bump needs no flag (users see no difference).
Dependabot closes its own pull requests once the dependency is updated. Updates to GitHub Actions live in `.github/`, which Agents
may not edit, so they are only reported.

  python3 maintenance.py        Env: FACTORY_PAT, FACTORY_GH_TOKEN, GITHUB_REPOSITORY.   Switch: limits.maintenance.enabled
One Intake per app and set of updates (a failed one is not refiled; its fix request is), one open at a time per app.

### template_sync.py

Template sync: a Starter Template improvement reaches the Managed Apps that were seeded before it.

An app is seeded once from `templates/starter/`. Without this, a better linter, test script or default never reaches an app that
already exists, and the learning loop's fixes only help new apps. Each app carries `.factory-template`, the ai-factory commit its
template files correspond to (App Staging writes it; an older app has none, so the commit current when its repo was created is
used). When the template has changed since then, this files one Update App Intake per app that gives the coder the template's own diff
and starts it. The coder applies it to the app's corresponding files, keeps the app's own code, and writes the new commit into
`.factory-template`.

  python3 template_sync.py       (run from a full checkout of ai-factory; nightly by template-sync.yml, or by hand)

Only files an Agent may change are synced. The protected ones (.github/, fly.toml, fly/, feature-flags.ts) are listed in the
Intake as "not applied" for a person. One Intake per app and target commit (a failed one is not refiled; its fix request is), and one
open at a time per app. Env: FACTORY_PAT, FACTORY_GH_TOKEN, GITHUB_REPOSITORY.

## orchestrator/monitoring/

### benchmark.py

Whole-run benchmark: is a candidate model (or prompt) as good as the current one, and what does it save?

The Factory swaps models as better, cheaper, faster or more specialised ones appear. A swap is only safe if it is measured on the real thing,
the whole Build Run, not on one role in isolation. This runs a fixed SUITE of Intakes (agents/benchmark/suite.json) through the real Build Run
workflow against one disposable bench app, resets that app to a frozen commit before every task, and scores each task with an ORACLE: `api_check`
scenarios run against the deployed app, plus the outcome the task expects. Code decides pass or fail, never a model. The result is compared with
the accepted BASELINE (agents/benchmark/baseline.json) under fixed RULES (agents/benchmark/rules.json), and the report says whether to accept the
candidate and how much cost and time it saves.

  PYTHONPATH=orchestrator python3 -m monitoring.benchmark plan   [--candidate coder=ID,tester=ID] [--tasks a,b]    what a pass would do and cost (no spend)
  PYTHONPATH=orchestrator python3 -m monitoring.benchmark run    --label NAME [--candidate ...] [--tasks ...] [--execute]   a pass (without --execute it only prints the plan)
  PYTHONPATH=orchestrator python3 -m monitoring.benchmark compare RESULT.json                                       compare a result with the baseline
  PYTHONPATH=orchestrator python3 -m monitoring.benchmark accept  RESULT.json                                       make a result the new baseline
  PYTHONPATH=orchestrator python3 -m monitoring.benchmark freeze                                                    record the bench app's current main as the frozen base

A candidate is a branch whose agents/profiles.yml names the candidate models; the runner files each task as an Update App Intake labelled `benchmark`, dispatches the
real `plan.yml` from that branch (so the planner it measures is the branch's), then dispatches the real `build-run.yml` from that branch for each child the plan filed,
in order, so production code carries no "benchmark mode" (the label only keeps the production workflows from starting the children with the production models). The branch also pins the limits that would make passes incomparable (no flag retirement
ride-along, a short watchdog, no daily cap). See docs/benchmark-protocol.md.

### canary.py

Model canary: find out that a pinned model is gone before an unattended night run does.

Models are retired and replaced. Each night this sends a one-token request (a fraction of a cent) for every model in agents/profiles.yml: each
role's `model` and its `fallback_model`. If a primary is no longer served, the Build Run would fall back to the role's fallback (build_run.check_models)
and the owner should choose a new pinned model; if a fallback is gone too, the next retirement stops runs. Either way one deduplicated
`model-drift` issue in ai-factory says which role and which model, and it closes itself once every model answers again. Nothing is changed here.

Env: DEEPINFRA_API_KEY, FACTORY_GH_TOKEN, GITHUB_REPOSITORY.

### dashboard.py

A static dashboard of the Factory's Build Runs, and a daily digest.

Each Build Run uploads its Report as an artifact, and artifacts expire. This keeps the history: it collects
the Reports of runs it has not seen yet, merges them into `history.json`, and renders `index.html` beside it.
The scheduled workflow (.github/workflows/dashboard.yml) keeps both files on the `factory-data` branch, which
GitHub Pages can serve if it is enabled for that branch; the digest goes to the workflow's run summary.

No server, no database and no new always-on service. The pure functions (summarize, merge, metrics, render)
are unit-tested; `collect` and `main` talk to GitHub through `gh`.

Usage: dashboard.py <data-dir>        (env GH_TOKEN and GITHUB_REPOSITORY; GITHUB_STEP_SUMMARY optional)

### fly_audit.py

Find Fly apps nobody owns: machines that bill while nothing in the Factory knows about them.

A Fly app is owned if it is Factory infrastructure (`limits.fly_infra_apps` in agents/profiles.yml, plus GrowthBook) or a
Managed App: a repo in the Factory owner's account whose description carries the `Intake: <factory repo>#<n>` marker App
Staging writes. Anything else is an orphan, for example after a failed teardown or an App Staging run that stopped between
creating the Fly app and the repo. Nothing is deleted here: the audit keeps one open `fly-orphans` issue in ai-factory,
updated when the list changes and closed when it is empty, and the person decides (teardown.yml removes a Managed App).

Env: FLY_API_TOKEN, FLY_ORG (the Fly organization slug, default `personal`), FACTORY_PAT (read repos), FACTORY_GH_TOKEN
(the Actions token, used for the issue), GITHUB_REPOSITORY.

## orchestrator/planning/

### file_children.py

Filing a plan's child tickets: one sub-issue per change set under the Intake, each with its complete instructions and its marker, dependencies
first, the dependencies as GitHub blockers. Filing is idempotent (a parent that already has children is left alone) and all-or-nothing (if any
call fails, the children made so far are closed and the error is raised, so the Intake can be planned again with no orphans).

### fix_for.py

STEP 2.1, 2.4: planning a bug Intake that fixes a failed child (its body carries a `fix-for` marker, shared/child_tickets.read_fix_for). The plan is exactly one
change set, an ordinary child: the planner decides its flag like any other, and the Build Run names it `issue-<own number>`. The planner is told to plan one
slice, the plan gate refuses more than one, and the child is filed with `fix_for` and `fix_attempt` so the Retrospective counts the attempts. The failed child
is already blocked by the bug Intake (try_fix/file_bug.py), so nothing here blocks anything.

### plan_run.py

The planning process (STEP 2.1 to 2.5): read an Intake, ask the planner Agent for a plan, check it, and file one child ticket per change set. It is
its own workflow (`plan.yml`), started by the Intake's label, before any code is written, and it files at least one child. `PlanRun` is the
sequencing over parts that are tested alone (validate_plan, triage, secrets_check, render_child, file_children); everything it touches in the
world (the Agent, GitHub, the clock) is handed in, so each ending is tested without any of them.

Endings: planned (children filed), refused (the Factory cannot build it), awaiting_secret (the owner sets secrets, then re-adds the label),
needs_human (a blocking question, a rejected plan, a request that cannot be read), skipped (a child ticket, or an Intake already planned). Every
ending but planned and skipped comments on the Intake and leaves it as it was: retry = edit the issue, remove its label, add it again.

Usage: python -m planning.plan_run   (PYTHONPATH=orchestrator; env as set by .github/workflows/plan.yml)

### triage.py

Triage: what the Factory refuses before it spends anything.

Two checks stop a request before a coder, tester or reviewer is paid for:

  secrets   Intake issues and the app repos are PUBLIC. A request that contains a real secret value (a private key block, a provider token,
            a password assignment) is refused at once, and the comment says what kind of thing was found and never repeats it. The owner
            should rotate it, because it is already visible on the Intake issue.
  feasible  The planner judges whether the request can be built here at all: inside the pinned Express + React stack, with free dependencies,
            and without payments, a third-party secret or API key, or personal data. When it cannot, the planner says so in its plan
            (`feasibility`) and the Build Run ends as `refused` after the planner call, nothing built, nothing retried.

Nothing here asks a person: a refusal is a clear answer with the reason and what would make the request possible, on the Intake issue.

### validate_plan.py

Plan validation for the planner role (agents/prompts/planner.md).

The planner Agent turns a larger Intake into a plan: requirements, the questions only a person can answer, and
an ordered set of change sets, each one Build Run's work with its own acceptance criteria and flag. This module
is the deterministic gate between that plan and any coding: nothing is dispatched from a plan that fails it, and
a plan with an unanswered blocking question ends in a needs-human Issue instead of a guess.

The plan format (JSON):

  {"requirements": [{"id": "REQ-1", "text": "..."}],
   "assumptions": ["..."],
   "open_questions": [{"id": "Q-1", "text": "...", "blocking": true}],
   "change_sets": [{"id": "CS-1", "title": "...", "requirements": ["REQ-1"], "depends_on": [],
                    "criteria": ["AC-1: ..."], "verification": ["..."], "flag": "slug-or-null",
                    "internal_only": false, "out_of_scope": ["..."]}]}

Used by the Build Run for an Update App Intake (`BuildRun.plan_change`): one change set becomes that run's task; several
are filed as child Update App Intake issues by `planning.file_children`, each its own Build Run, in this order.

## orchestrator/request/

### file_intake.py

Filing an Update App Intake for a Managed App. Every automated source (template sync, maintenance, production feedback, flag retirement) files
through here. The issue is created with the PAT and its `update-app-intake` label at creation is what starts planning (STEP 1.3, 2.1): an event made by
the Actions token does not start workflows, so the Actions token files nothing that must start.

## orchestrator/retrospective/

### app_state.py

Where each Managed App stands, kept in GitHub issues the Orchestrator maintains.

- The **App State issue** (label `factory-state`) in each Managed App's repo: its recent Build Runs and every flag
  a Build Run released, with the flag's last known state. This is how a person, or the next Build Run, learns
  "what is in flight, what is released" without reading logs. It is an issue, not a file on `main`: a commit
  would redeploy the app, race the release step, and break "only the coder's work reaches main".
- The **registry issue** (label `factory-registry`) in ai-factory: one row per Managed App, linking each State issue.

Each body carries its data as JSON in an HTML comment, so a rewrite never has to parse the tables. `finalize`
calls `update_state_issue` and `update_registry` after every Build Run, best effort: a failure here never changes
a run's outcome. The rendering functions are pure and unit-tested.

### close_child.py

Closing a child and moving the plan on (STEP 6.1, 6.3, 6.4). A child that finished is closed and starts the next one that is waiting; one that
stopped loses `proceed-with-change`, so adding the label again retries it (a label that is still there cannot fire again). The children are the
parent's sub-issues, and what a waiting child waits for is its GitHub blockers: it is ready when every blocker is closed. The last child to
close closes the parent.

### event_verdicts.py

STEP 6.2, 6.7: the Retrospective's verdict on each failure event. The Agent names, per event, a verdict (`fix` or `record`), a target (`managed_app` or
`factory`), a cause and a reason; this file turns that, or the lack of it, into a verdict for every event. The rules are code, not prompt:
  a failure is always fixed (the Agent cannot downgrade it); a warning is fixed only when the Agent says `fix` and gives a reason;
  with no answer a failure is `fix` and a warning is `record`; at most `fix_events_per_app_per_day` warnings are fixed per app per day.

### improvement_issues.py

Step 3: each improvement the reviewer or tester suggested for the Factory becomes a `factory-learning` issue in ai-factory, deduplicated and capped per run. One for
the Managed App is a failure event (try_fix/collect_events.py) that the Retrospective judges; no suggestion issue is filed in the app's repo any more.
The Agents only suggest; the Orchestrator files.

### judge_events.py

STEP 6.7: judge failure events that have no Build Run (a scan of production errors, escaped defects, a failed staging check). One model call for the
whole batch, from the event records and the App State only, under `retrospective_cost_cap_usd`; the answer goes through the same rules as a run's
(event_verdicts.decide). Filing a ticket for a `fix` verdict is Try Fix's job (tickets 15c and 15d); this file only returns and prints the verdicts.

Usage: python -m retrospective.judge_events <events.json> <verdicts.json>   (PYTHONPATH=orchestrator; DEEPINFRA_API_KEY)

### run_audit.py

Check a finished Build Run's Report against the design invariants (docs/invariants.md).

The unit tests prove the code does what the rules say; this checks that a real run did. It reads only the
Report (`state.json`, as `finalize` writes it) and returns the rules it finds broken, so a bug that only
shows up in production, or a run that went around the code, still leaves a record. `finalize` stores the
result in the Report (`audit`) and the Summary; the retrospective turns a violation into a lesson.

Pure functions, no network. Usage: audit.py <build-run-report.json>   (exit 1 if anything is violated)

### run_retrospective.py

After every Build Run, released or not: record what it taught, propose the fix as a PR, and report back on the story that started it (STEP 6.2).
Runs as its own workflow step after `finalize`, on every run, and never fails the run. Facts, lesson issues, minor findings, improvements, the
Retrospective Agent and its learning PR, the fix request and the story report each have their own file in this folder.

Usage: python -m retrospective.run_retrospective [lesson <issue> | auto-merge-check <base> <head>]   (PYTHONPATH=orchestrator)

## orchestrator/shared/

### api_check.py

api-check: the tester states what a request should return; this observes what it does return and compares them.

The tester agent used to run `curl` and judge for itself whether the answer was right, and the seeded-bug benchmark
(agents/smoke-tester) showed that judgement slipping: a 200 where the spec says 201 was waved through. Here the model's
job is only to say *which* checks the spec calls for and what each expects. The comparison is mechanical, and every result
is appended to a log (`$API_CHECK_LOG`) that the Orchestrator reads, so a failure the helper saw cannot be reported as a
pass, or left out of the report (build_run.reconcile_api_checks).

  python3 api_check.py checks.json [--base https://app.fly.dev]

Env: PREVIEW_TOKEN (sent as X-Preview-Token for a check with "auth": "preview"; never printed or logged),
API_CHECK_BASE (the base URL if --base is not given), API_CHECK_LOG (a JSONL file each result is appended to).
Exit status 0 if every check passed, 1 if any failed, 2 if the file is unusable. Standard library only.

A checks file is {"checks": [...]} (or the list itself). Each check:

  {"id": "create-201",                         unique; the report refers to it
   "name": "POST /api/notes with valid text answers 201",
   "request": {"method": "POST", "path": "/api/notes", "auth": "preview" | "none",
               "json": {"text": "a"}  or  "body": "raw text, e.g. malformed JSON",  "headers": {"X-Other": "v"}},
   "expect": {"status": 201 | [200, 201],
              "json": {"id": "<integer>", "text": "a"},     a subset match: extra keys in the answer are fine, lists must
                                                            be the same length, and "<number>", "<integer>", "<string>",
                                                            "<nonempty-string>", "<boolean>", "<array>", "<object>",
                                                            "<null>" and "<any>" stand for any value of that kind
              "body_contains": ["..."], "body_not_contains": ["..."],
              "headers": {"content-type": "application/json"}, "header_absent": ["x-secret"]},
   "capture": {"note_id": "id"}}               remember a value from the answer (dotted path, e.g. "items.0.id") and use
                                               it as {note_id} in later paths and JSON

Checks run in order, one request each, 15 seconds at most per request, at most 100 per file, and only against the base URL.

### app_state_record.py

The format of the App State record, which Maintenance, Flag Lifecycle, Bugs and the Build Run all read: each issue body carries its data as
JSON in an HTML comment, so a rewrite never has to parse the tables. The App State issue (label `factory-state`) lives in each Managed App's
repo; the registry issue (label `factory-registry`) in ai-factory has one row per Managed App.

## orchestrator/staging/

### read_staging_child.py

The first thing the staging workflow does with a `kind: staging` child (STEP 3.1): decide whether it may be staged now, and say what to stage. The
child's marker says it is the staging child; its form names the app; the parent Intake holds the owner's request and cost cap (the repository's
INTAKE.md is written from it) and is read for that and nothing else. Limits: one Managed App through staging at a time (`max_simultaneous_build_runs`).

Usage: python -m staging.read_staging_child   (env: FACTORY_REPO, ISSUE_NUMBER, GH_TOKEN); prints KEY='value' lines for the shell, or the reason on
stderr and exit status 3 when the child may not be staged.

### verify_infrastructure.py

What staging proves before the first business child may start (STEP 3.2): the app that was seeded is built, deployed and wired to everything it
needs. Deterministic checks, in this order, each with its own result; none of them is an Agent's opinion. Everything outside (HTTP, GitHub,
GrowthBook, the clock) is handed in, so the checks are tested without any of it.

  ci_green         the seed commit's Test Gate, Build and Deploy to Fly runs all finished green
  deploy_healthy   `/api/health` answers 200 with `{"status": "ok"}`
  flag_service     GrowthBook has the app's own SDK connection (the app starts only once its flag provider is ready, so a healthy deploy
                   also shows the app reaches the service)
  preview_token    a request carrying the app's Preview Token is given the preview cookie, and one carrying a wrong token is not
  secrets_present  the repository has the secrets staging sets, and every secret the request declared
  smoke            the deployed app serves its front page

Usage: python -m staging.verify_infrastructure   (env: FACTORY_REPO, ISSUE_NUMBER, APP_NAME, SEED_SHA, FACTORY_PAT, GROWTHBOOK_ADMIN_PAT,
PREVIEW_MASTER_SECRET, GITHUB_STEP_SUMMARY, optional FAILURE_EVENTS_FILE); exit 0 when every check passes. When a check fails, one failure event per failed check is
written to FAILURE_EVENTS_FILE for the Retrospective to judge (STEP 6.7).

## orchestrator/try_fix/

### collect_events.py

STEP 6.2: the failure events of one Build Run, from its facts (retrospective/run_facts.py). The run's own ending is the one `failure`; the
warnings are the things that did not stop the run but are worth a look (a dark-only test failure, a check that could not be run, a minor finding,
an improvement for the app, a flag that was missing). The Retrospective gives each event a verdict; nothing here decides to fix anything.

### event.py

STEP 6.2, 6.7: the failure event, the one record every source of trouble writes so the Retrospective can judge it. An event is a plain dict:
  key, source, severity ("failure" or "warning"), app, story (the story issue number, or None), fingerprint, summary, evidence, flag, released
`released` is True when the story's flag was released and is still on, False when it is dark (never released, off, or switched off by the
watchdog), None when the source cannot tell (the Bugs domain fills it in from the App State).

### factory_fix_request.py

The Factory and information routes (STEP 7.2, 7.5): an issue in ai-factory for a cause that is not the app's. A Factory cause (a prompt, the planner, the
Starter Template, the orchestrator) is also given to the retrospective Agent, whose learning PR resumes the failed child when it merges
(`resume_after_merge`); the issue records which child that is. One open fix request per failed child and route: a run that fails again adds a comment.

### file_bug.py

STEP 7.1, 7.2, 7.4, 8.1, 8.4: file the bug for an event the Retrospective judged worth fixing, once the Try Fix Agent has written its text (write_bug.py). The
ticket is always an Intake, so the planner plans it like any other change and a fix has the same limits as any change:

  dark story    the event belongs to a planned child that is still open and whose flag is not released (never released, off, or switched off by the watchdog,
                STEP 5.5): the failure is commented on that story, and the bug Intake carries a `fix-for` marker, so planning makes exactly one ordinary child. The failed
                child is blocked by the bug Intake and waits, so it resumes only when the Intake closes (retrospective/close_child.py), behind its own flag, and is never
                started again unchanged. A fix of a fix counts as the next attempt; after `fix_attempts_max` the failed child is held `needs-human`.
  released      the flag was released and is still on, or there is no story: a regression. A new bug Intake with no marker that nothing waits for; the story is told where it is.
  factory       the cause is the Factory's, or none was named: one fix-request issue in ai-factory from the same template. A planned child that failed is held
                `needs-human` until the fix merges (resume_after_merge.py) or a person decides.

One open bug per event key (the key is in the title); a repeat comments. Never raises ChildTicketError to the caller: a refusal part way takes the bug back.

### file_events.py

STEP 7: file the bugs for events with no Build Run, after the Retrospective judged them (`retrospective.judge_events` writes the verdicts). Each `fix` verdict gets its
text from the Try Fix Agent and is filed exactly as for a failed run (file_failure.py); a `record` verdict files nothing. Used by production-feedback.yml.

Usage: python -m try_fix.file_events <verdicts.json>   (PYTHONPATH=orchestrator; env GITHUB_REPOSITORY, FACTORY_PAT, FACTORY_GH_TOKEN, DEEPINFRA_API_KEY)

### render_bug.py

STEP 7.6, 7.1: the bug template. One text for every bug: What happened, How it was found, Root cause, What it would take to resolve, Requirements, Target, and the
log of failure and solution comments. For an app fix the text is the request of an Intake, written under the form headings the planner reads
(`App name`, `What should change?`), so a bug is planned exactly like any Update App Intake; for a Factory fix it is the body of an issue in ai-factory.
The hidden `<!-- bug:KEY -->` marker is the event's key: one bug per key. In an Intake it goes first, because the form's last section runs to the end of the body.

### validate_bug.py

STEP 7.6: the check on what the Try Fix Agent wrote, before it becomes a ticket. Returns the cleaned document and the problems; any problem means the
Orchestrator writes the ticket itself (write_bug.fallback). A secret value is never allowed into a public issue (INV-50), and a requirement the
planner and tester cannot check ("improve", "consider") would only move the vagueness into the work.

### write_bug.py

STEP 7.6: write the bug ticket's text for an event the retrospective judged worth fixing. The Try Fix Agent has one job: how it was found, the cause (already
named, never decided here), what it takes to resolve and checkable requirements. It is one model call with no tools under its own capped credential; the
answer is validated (validate_bug.py), and when there is no key, the call fails or the answer is unusable the Orchestrator writes the same four fields from
the facts (fallback), so a filing never depends on the model. It plans nothing and splits nothing: that is the planner's job.

## Rationale that used to sit in comments

The reasons behind individual lines and functions, by file and function, moved out of the code. Prefer encoding a reason in a name before adding it here.

### agents/replay/replay.py

`module`
- The Managed Apps these commits came from have been torn down; their history is kept as a bundle beside this script. Fall back to GitHub for an app that still exists.

### agents/smoke-coder/run.py

`validate`
- The scorer itself: an untouched checkout is "no commit"; a committed reference solution passes.

### agents/smoke-tester/run.py

`module`
- its helpers: base copy with deps installed, env, mount, cost

`judge`
- Score one tester report against what the fixture expects. Returns {"outcome": caught|missed|false_alarm|correct|unusable, "right_reason": bool|None, "failed": [...]}. `doc` is the report as parsed (or None). The Orchestrator's own reading is used: derive_test.
- Nothing was run (every check not_run or blocked: seen when the tester could not execute curl). The Orchestrator rightly refuses to release that, but it says nothing about whether the tester can find this bug, so it is not counted either way.

`summarize`
- only runs that actually tested something

`GrowthBookStub`
- Serves the SDK payload GrowthBook would: no flags (a feature flag that is not in the payload reads as off, which is how a dark feature behaves).

`validate`
- an unobservable bug fails no check

`one_run`
- kept: without it a run that quits at once cannot be diagnosed
- the Orchestrator reads the report this way: the helper's observations outrank the tester's judgement
- say why, from the agent's own output

### agents/smoke/run.py

`module`
- Optional: "low" | "medium" | "high", sent as reasoning_effort on every call.
- The schema the Orchestrator's single-call reviewer sends, so the smoke test checks the model against what it will really be asked.
- The real single-call reviewer prompt (agents/prompts/reviewer-fast.md plus the shared rubric), rendered the way the Orchestrator renders it. A fixture is an update unless expected.json says "first build".
- T1
- T2
- replay exactly as returned, incl. reasoning_content if present
- FIXTURES=name,name limits the T5 run to those fixtures (to repeat a flaky one).
- T3
- T4
- T5: every (fixture, trial) is an independent call, so they run in parallel. A trial that errors (provider overload, timeout) after the retries says nothing about the model, so it is reported separately and does not count against the fixture.

`chat`
- One API call. Retries overload (429), server errors (5xx) and timeouts with backoff: those say nothing about the model, and counting them as wrong verdicts made a busy provider look like a regression.

`parse_verdict`
- The Orchestrator derives the verdict from the findings instead of trusting the model's own field.
- a blocking finding the fields do not back is minor, as at run time

### orchestrator/build_run/endings.py

`Refused`
- The request cannot be built here (a real secret in public text, or the planner judged it infeasible). The run ends `refused`: nothing was built, so nothing is rolled back, retried or filed as a failure.

`AwaitingSecret`
- The plan declares secrets that are not all set as GitHub Actions secrets on the app's repository yet. The run ends `awaiting_secret`: nothing was built, and it is not a failure, so nothing is retried or learned from. Adding `proceed-with-change` again checks again.

`Regression`
- The tester saw behaviour that was live before this change stop working (`test_impact`). finalize rolls the deploy back through CI.

`PipelineFix`
- CI or the deploy failed because of the code, and the coder has committed a fix locally. The fix goes through the reviewer before it is pushed, like any other commit; `head` is that local commit.

`module`
- spend at or above this share of the cap makes an Agent's failure a budget ending

`ending_for`
- How a NeedsHuman stop is reported. An Agent whose credential has run dry just fails to produce its file (first seen when a tester ran out of a $0.08 cap and the run was reported as `needs_human: no valid output file`), so a stop of kind `other` with the cap already spent is a budget ending, not a mystery.

### orchestrator/build_run/gate_release.py

`ReleaseStep.archive_retired_flags`
- the flag's story hears that its flag is gone

`ReleaseStep.release`
- Switch on the story's own flag(s). A flag that does not exist is never created here (flag_lifecycle/missing_flag.py): if the code reads it the change is dark with nothing to turn it on, which fails the run; if the code does not read it the change is already live, which is noted and left alone.

`ReleaseStep.watch_release`
- After a release, watch the app (flag_lifecycle/watchdog.py). A run of failed health checks, or a rise in error-level log lines, switches the flags this run released off by itself (never one that already existed, which the owner controls) and ends the run as `watchdog_disabled` so finalize opens the Issue. The flag is the rollback lever, and the release step never turns it back on. The outcome was set just before this call and is not on disk yet. Save it now: the watch below can take minutes, and a run cancelled during it must still report `released`, not look like a crash.

### orchestrator/build_run/review_code.py

`finding_support`
- Why a finding the reviewer called blocking cannot block, or None when its fields support it. It blocks only if its category is one that can (not style, duplication or other) and its evidence is something to act on: a `repro` (a command or check that shows it) or a citation (a file and line). An opinion never blocks.

`banded_findings`
- The reviewer's findings with each one's band decided from its structured fields, never from the model's label alone. A finding the reviewer called blocking keeps that only if `finding_support` finds the fields back it; otherwise it is minor, with the reason in `downgraded`. A minor finding is never raised. A document whose findings lack the structure raises ValueError, so the caller asks again instead of trusting a label (the same way a missing findings list is handled).

`module`
- The two files every route passes through: the reviewer must see them even when unchanged, to judge how routes are mounted and how flags fail closed.
- Detail a finding may carry so the coder can act without exploring; all best-effort, "" when not applicable.

`flag_findings`
- Findings about this change's own flags that need no judgement, so the reviewer is not asked for them and the severity is fixed: a flag in `flags.json` that no code outside the tests reads (it would be released with nothing behind it), and a flag whose description does not start with an issue reference (it must point back to its story). Both are minor. `git(*args)` returns a git command's stdout ('' when it fails), run in the app checkout.

`suppression_findings`
- A minor finding when the change adds a lint or type-check suppression (`eslint-disable`, `@ts-ignore`, `@ts-nocheck`). The lint config is the Orchestrator's, so the coder cannot loosen a rule for the whole app; a suppression is the local way around one, so it is named where the retrospective sees it and can ask for a better rule or default. Always minor: one is sometimes right. `git(*args)` returns a git command's stdout ('' when it fails), run in the app checkout.

`ContextTooLarge`
- The change does not fit in one prompt; the caller falls back to the exploring Agent.

`FastReviewFailed`
- The single call produced nothing usable; the caller falls back to the exploring Agent.

`build_review_context`
- Everything the reviewer would otherwise go and look up, in one message.  `git(*args)` returns a git command's stdout ('' when it fails), run in the app checkout. Raises ContextTooLarge when the change cannot be shown whole, so a partial view never stands in for a review.
- The spec is the change being made now (the child's task). INTAKE.md describes the app as first built, not this change, so it stands in only when no spec was given.

`ReviewCode.fast_review`
- The reviewer as one model call over a prompt the Orchestrator assembles (no tools, no exploring). Returns (document, cost, usage) like agent_json, or raises ContextTooLarge or FastReviewFailed, in which case the caller uses the exploring Agent.

`ReviewCode.review_before_push`
- The reviewer reads the local commit before anything is pushed or deployed, so code it blocks never reaches `main`. A single model call over a prompt the Orchestrator assembles, or the exploring Agent when the change is too big or the call fails. Returns (clean, blocking findings, minor findings).

### orchestrator/build_run/run.py

`BuildRun`
- Sequencing only: `run` calls each step in order. Each step's code is in the mixin named above (one file each), over this object's state.
- the flags this run retires in passing (set in setup)
- the failed child this child fixes (its marker's `fix_for`), set in setup
- the flag this run named for the story (flag_slug.py); it is switched on at release whether or not this run created it
- slug -> number of the story each released flag came from (from the State issue)
- the secrets recorded on the Intake, checked at the start of the run (`setup`)
- set in __init__ from AGENT_USER; a class default so a bare test instance runs Agents as the same account
- The reviewer sees the commit before it is pushed, so code it blocks never reaches `main`; only reviewed code is pushed, and it deploys dark behind its flag until the tester has passed it.
- Nothing failed, but checks were blocked or not run. The coder cannot fix that, so it gets no round for it: the tester looks again at the same deployed commit, and a run that still cannot verify it stops for a person.

`BuildRun.__init__`
- limits.agent_isolation: user -> the workflow created this unprivileged account and put the work directories where only it and the runner can reach them; every Agent then runs as it.
- every Build Run is a planned child of an existing app; staging is not a Build Run

`BuildRun.stop_when_live_and_failing`
- The change is live with no gate (nothing reads its flag), so a failure is a failure in production: roll back.

`BuildRun.write_findings`
- Kept on a clean pass too: the minor findings of a run that ships are what the retrospective learns from.

### orchestrator/build_run/ship_code.py

`module`
- a workflow run GitHub ended before any job started: no log to diagnose

`ShipCode.wait_run`
- Test Gate and Build finish at different times and each starts a Deploy run; the first one finds the other not done and skips its deploy job. That run says "success" but deployed nothing, so it is not the run to wait for.

`ShipCode.pipeline`
- GitHub did not run it (no jobs, no log), so there is nothing for the Pipeline Agent to read: say so, and spend nothing.

### orchestrator/build_run/start_build.py

`start`
- Only a planned child starts a run: a sub-issue of an open plan whose body carries the `factory-plan` marker naming that plan.

### orchestrator/build_run/suggestions.py

`module`
- per reviewer or tester document, so one noisy model cannot flood the trackers

`improvements_from`
- The system improvements a reviewer or tester suggested: [{source, target, summary, evidence}]. `target` is `managed_app` (the app's own backlog) or `factory` (prompts, template, orchestrator). Anything malformed is dropped; the Agents only suggest, the retrospective decides what is filed.

### orchestrator/build_run/ui_check.py

`settle`
- What the page shows once it has had a few seconds to settle, with the problems found. A page updates after a network call, so the expectations are re-read until they hold or the patience runs out (the way Playwright's own assertions wait), and only the last reading counts. Without this a correct page fails because the check looked a moment too soon.

`open_start_page`
- sets the HttpOnly preview cookie

### orchestrator/build_run/verify_deployed_app.py

`module`
- the helper the tester calls (see api_check.py)
- its browser counterpart (see ui_check.py)
- Evidence that says, in the tester's own words, that it did not observe the thing it is reporting on. A model that writes this and still marks the check `passed` (seen in the first real run on an unobservable requirement) has not verified it.

`check_state`
- One tester result's state. `status` is one of CHECK_STATES; a report that only has the older boolean `passed` is read as passed or failed. Anything unrecognised counts as failed. A check marked `passed` whose own evidence admits it was not observed counts as `not_run`: it keeps the change from releasing.

`reconcile_helper_checks`
- The tester's report with a helper's observations ranking above its judgement. A result that cites a check (in `field`, `api` or `ui`) which failed cannot stay `passed`; one that cites a check the helper never ran cannot either; and a check the helper saw fail that no result mentions is added as a failure, so the tester cannot leave out what it was shown. Results that cite no check of this kind are untouched.

`derive_test`
- (passed, failures). passed is derived from the results, and every new flag needs a result. Only a check in the `passed` state passes: `failed`, `blocked` (something outside the app stopped the check) and `not_run` all keep the change from releasing. With no new flags (an internal change) the results test the Intake's requirements, and there must be at least one.

`test_impact`
- What a test pass that did not pass means for production: `regression` when a check of behaviour released *before* this change (`scope: existing`) failed and a helper observed it (the helper's log, not the model's word, is what makes it a regression), `dark_only` when only the new, still-dark change fails, `ok` when nothing failed. A regression is the one case that takes the live app back on the previous deployed version (never a git revert); a broken dark feature stays dark and is fixed forward.

`bugs_from`
- The tester's failed checks as notes for the retrospective, which adds them to the story's own issue (the Update App Intake that started the run, so the retry sees them) and never opens a new issue for them: [{kind, flag, check, evidence, repro}]. `regression` is a failed check of behaviour that was live before the change; `dark` is a failed check of the new change, which stays dark. Only `failed` is a bug: a check that was blocked or not run was not seen to fail. The tester only notes them; it files nothing, and nothing is taken out of git because of them.

`VerifyDeployedApp.test_deployed`
- The tester drives the deployed app (dark behind its flag, via the Preview Token; a change without flags is tested against the child's requirements) and says what a failure means: `regression`, `dark_only` or `ok` (`test_impact`). It has its own HOME for OpenHands and its own checkout of `head`. Returns (passed, failures, impact).
- No usable report, but if a helper saw something fail that is a finding the coder can act on: use it instead of stopping for a person. With nothing failed there is nothing to act on, so it stops as before.
- so the next round's tester sees the failures the helper added; best effort, never a reason to stop the run
- this pass's failures: a bug fixed by the next round is no longer a bug

### orchestrator/build_run/write_code.py

`WriteCode.secret_problem`
- a name already in the app's secrets.json was accepted by an earlier run

`WriteCode.check_problem`
- Run the app's own `npm run check` (type-check and lint, the Test Gate's first step) on the coder's commit, as the Agent user, and return what to tell the coder when it fails, so a mechanical error costs a coder attempt and not a review, a push and a CI run. It only reads: the formatter stays the coder's. None when it passes, the app has no such script or it could not be run.

### orchestrator/flag_lifecycle/dark_feature.py

`is_dark_broken`
- Whether the run left a dark feature behind: it pushed code behind a flag and ended without releasing it (or with the watchdog having switched the release off, or the tester having found a regression and the deploy been rolled back). The code stays in `main`, behind a flag that is off, and is fixed forward by a fix child. The flag is the identity of a dark feature, and its story issue (`flag:<slug>`) carries this label; `flags.json` does not, because every edit to it deploys.

`label_dark_feature`
- the story names its flag, released or not

### orchestrator/flag_lifecycle/flag_slug.py

`ensure_feature`
- The extras are the pointer back to the story; if GrowthBook refuses them the flag is still created without them.

### orchestrator/flag_lifecycle/release_features.py

`check_flags`
- Looks at each flag in `flags` without changing anything. Returns (keys to switch on, keys left as they are, slugs that do not exist). A flag is switched on only if it exists, is off in production and is the story's own (`own`: the flag this run named for the story and the flag a retried story keeps); every other existing flag is left exactly as it is.

### orchestrator/flag_lifecycle/retirement_check.py

`module`
- one line per flag to retire

### orchestrator/flag_lifecycle/retirement_selection.py

`choose`
- The proven flags that ride along with a run, and {slug: story number} for the flags the State issue knows: none picked for a fix child (`eligible` is false). A task that names flags itself (`retire-flag:` lines, from an owner's Intake) retires those too. Only flags still in the manifest at the run's base count. A failed lookup never stops the run.

### orchestrator/flag_lifecycle/set_flag.py

`main`
- The API wants the environment's rules with the switch (the watchdog sends rules too); send the current ones back unchanged.

### orchestrator/flag_lifecycle/watchdog.py

`watchdog_trip`
- The reason to switch a just-released flag off, or None. `samples` are in time order, each {"healthy": bool, "errors": int}. Trips on `max_failures` health failures in a row, or on the error count rising `max_new_errors` above what the app logged before the release.

`watch`
- Watch the app for `watchdog_minutes` after a release. Returns (minutes watched or None if the watch is off, the reason it tripped or None, the keys that could not be confirmed off). A trip calls `disable(keys)`, which switches the released flags off (never one that already existed) and returns the ones still on.

### orchestrator/maintenance/template_sync.py

`module`
- the coder regenerates it with npm install

`main`
- no paths would diff everything

### orchestrator/monitoring/benchmark.py

`compare`
- {accept, reasons, deltas, improvement} for a candidate pass against the accepted baseline under the rules. The candidate is accepted only if its pass count is within `max_pass_drop` of the baseline's, every task tagged in `must_pass_tags` that passed in the baseline still passes, its cost is within `max_cost_ratio` times the baseline's and its mean rounds rise by at most `max_rounds_delta`. A faster or cheaper candidate that stays inside those bounds is reported as an improvement.

### orchestrator/monitoring/canary.py

`main.status_of`
- an empty balance is its own alert (provider-blocked); it says nothing about this model

### orchestrator/monitoring/dashboard.py

`module`
- a change that shipped, or a build that needed no release
- the trailing window the payoff numbers are also shown over, to judge a change to the pipeline against what came before
- the owner's goal for one Build Run; a target, not a cap (the cap is `limits.cost_cap_usd_default`)

### orchestrator/monitoring/fly_audit.py

`main`
- the idle-app report goes in the run summary; it never fails the audit

### orchestrator/planning/file_children.py

`module`
- labels of the Intake that its children carry too

`file_children`
- Start the first one with nothing to wait for. Done last, so every child exists before the first run begins; the rest are started one at a time by `advance` as each finishes.

### orchestrator/planning/plan_run.py

`module`
- a workflow that ends this way succeeded; only needs_human is red

`PlanRun`
- `ask(task)` runs the planner and returns (plan document, cost, usage), raising NeedsHuman when no valid plan comes back; `comment(text)` posts on the Intake; `secret_names()` is the set of secrets the app's repo has; `tickets` is the parent's ChildTickets; `file(...)` is file_children.

`PlanRun.run`
- checked before the planner is paid for, on every planning

### orchestrator/planning/triage.py

`module`
- (kind, pattern). Specific shapes only, so an ordinary sentence about passwords is not refused.
- The Factory's own credentials: an app's secret may never use one of these names (the deploy step would copy the Factory's token into the app).
- Shapes of a real value that are safe to look for in code (no "password = ..." style, which ordinary code is full of).

### orchestrator/planning/validate_plan.py

`module`
- A change set that exists only to add tests. Every change set includes its own tests, so this one has no outcome of its own. A change set that retires or removes a flag. Its flag must be null: the feature is already live, so a new flag would switch it off. (A run that invented `retire-delete-flag` for this turned a live DELETE endpoint dark.)
- A change set that bumps dependencies is a different kind of work from retiring a flag; they ship and fail separately.
- An HTTP route or a screen element in the criteria: something a user or a client can reach.
- per change set: more means it is not one releasable, revertible slice
- a change set that would be "L" is split before it is filed

`validate_plan`
- a refusal has no change sets to check
- the staging change set serves the infrastructure, not a requirement of the request, so it may link none
- the Orchestrator names it after the story's issue (flag_lifecycle/flag_slug.py), so there is no slug to check

### orchestrator/retrospective/agent_run.py

`module`
- Where the retrospective Agent may propose changes. Never workflows (they hold the secrets), the Starter Template's protected files, or anything outside the Factory's own prompts, template, orchestrator, `ARCHITECTURE.md` and the glossary; nothing under `docs/`.

`record_agent_spend`
- own id: the ledger counts a run id once

`run_agent`
- Run the retrospective Agent in a copy of the Factory tree, as the unprivileged Agent user when isolation is on (the same account and self-check as the Build Run's Agents), with a scrubbed environment and a capped scoped key. Whatever it changes is carried back into `factory` by `apply_changes`, only for allowed paths; its answer is copied to `result_path`. Returns False when isolation is on but cannot be proven, in which case no Agent runs.

### orchestrator/retrospective/app_state.py

`render_state`
- A flagged change that was pushed and never released is a dark feature: it is listed (so a person can see it), and never taken for a released flag. Once it is released at last, the release above replaces the entry.

`update_state_issues.upsert`
- best effort; not every plan allows it

### orchestrator/retrospective/close_child.py

`ready_to_start`
- The number of the one child to start now, as a list (empty when none). `children` are the parent's sub-issues, each {number, state, labels}; `blockers(number)` gives that child's blockers as [{number, state}]. A child is ready when it is open, waiting, and every blocker is closed. At most one starts, and none while another is in flight (open with `proceed-with-change`: one app runs one Build Run at a time, and GitHub keeps only one pending run) or stalled (open with neither label: its run stopped, so it blocks the others until it is retried or closed).

`advance`
- After child `number` closed: close the parent if that was the last child, otherwise start the child that was waiting for it. Returns {"started": [numbers], "parent_closed": bool}. An issue with no parent (a child of no plan) does nothing. A closing bug Intake also moves on the plan of the child it fixed (settle_fix), and `started` then lists that plan's child.

### orchestrator/retrospective/event_verdicts.py

`decide`
- none named: the filing falls back to the cause (try_fix/route.py)

### orchestrator/retrospective/finalize.py

`finalize`
- The retrospective reads state.json, so the final state (audit, rollback) has to be saved there too.
- a refusal is answered on the Intake issue; there is nothing in the app repo to report
- the message already says how to try again

### orchestrator/retrospective/improvement_issues.py

`record_improvements`
- File what the reviewer and tester suggested for the Factory: a `factory-learning` issue in ai-factory (a comment when it is already open). A `managed_app` improvement files nothing here and is only listed for the report. Capped per run. Returns ([(factory issue number, already proposed)], [{target, summary, url}]) for the Agent and for the report.

### orchestrator/retrospective/judge_events.py

`answer`
- A batch of failures alone needs no opinion: every failure is fixed whatever is answered (event_verdicts.decide), so the model is asked only when a warning is in it.

`main`
- a credential limited to the cap, never the parent key

### orchestrator/retrospective/learning_pr.py

`module`
- Auto-merge is limited to additive changes to lint and formatter config in the Starter Template: they only add or tighten a deterministic check, and the Starter Template's own checks run on the PR first.
- A lesson's change should come with something that would have caught it: a smoke or replay case, a test.
- Emphasis a prompt change must not add: a louder sentence is not a fix, and a model that was told so still adds it.

`bad_fixture_reason`
- Why new reviewer smoke fixtures cannot be used, or None. `fixture_diffs` maps each new agents/smoke/fixtures/*.diff path to its text. The reviewer is shown a Managed App's change, so a fixture that is not a diff of app code (for example a diff of a Factory prompt) tests nothing the reviewer ever sees.

`lesson_has_fixture`
- True when a change set includes a test, smoke case or replay case alongside the fix. A reviewer smoke fixture only counts as a pair: the diff the reviewer is shown and its expected.json entry. The harness runs every fixtures/*.diff, so stray files in that folder would exercise nothing.

`open_pr`
- Validate what the Agent changed, test it, and open a PR. Returns the PR URL or None. The PR is labelled `auto-merge-candidate` only for an additive lint/formatter change; the PR checks workflow recomputes that and merges after its checks pass. Everything else waits for a human.
- drop anything outside the allowed paths rather than refusing the whole proposal
- leave the checkout clean for whatever runs next
- merging this fixes the Factory cause of a failed child, which then starts again (try_fix/resume_after_merge.py)
- the label must exist, and be on the PR from the start: the checks workflow reads it from the opened event

`propose`
- `failed`: {child, outcome, has_bugs} of the run that failed; when its cause is the Factory's, the PR says which child its merge resumes.

### orchestrator/retrospective/lesson_records.py

`module`
- signals recorded per run, so one noisy run cannot flood the tracker
- review passes at or above which a clean run is still a lesson (two fix rounds)

`lessons_from`
- A flag was missing when it was needed (flag_lifecycle/missing_flag.py): record it and the guess, so a pattern can be fixed in the Orchestrator or the app.

### orchestrator/retrospective/minor_findings.py

`module`
- per run, so one noisy review cannot flood the trackers

### orchestrator/retrospective/run_audit.py

`module`
- One review-and-test pass is a Review stage and a Test stage with the same round number.
- the call that crosses the cap completes (ARCHITECTURE.md: Cost guardrails)

### orchestrator/retrospective/run_retrospective.py

`main`
- a refusal, or a wait for the owner's secrets, is an answer, not a failure, not a failure to learn from or retry
- Not a lesson and not a fix request: nothing the Factory can change helps, and the Agent could not run anyway.
- The Agent looks at a lesson that came back after its fix, or has earned it (severe, or seen in enough distinct runs) and has no PR yet.
- STEP 7: each event judged worth fixing becomes a bug ticket written by the Try Fix Agent and filed as an Intake (try_fix/file_bug.py)
- app-side bugs go on the story's own issue; a fix child (above) already carries them in its requirements
- the story keeps what the run found, whether or not it released

### orchestrator/retrospective/story_report.py

`module`
- What each cause leads to, in words for the story.

`note_bugs_on_story`
- The bugs belong to the Managed App's own story, so they go on the Update App Intake that started the run, not into a new issue: the story gets the `bug` label and, unless the retry comment already carries them (`carried`), a comment listing them. The retry (the start label added again) is the bug Intake's job and is bounded by `fix_attempts_max`. Once per run.

### orchestrator/retrospective/tracker.py

`module`
- share of the words two issue titles have in common for them to count as the same problem

`content_words`
- "say" and "says" match

`similar_open_issue`
- The number of an open issue in `repo` that is about the same problem as `summary`, or None. Reworded titles still match (compared by their content words, ignoring the `[fingerprint]` and the Improvement/Suggestion prefix), so a repeat adds context to the issue that exists instead of opening a second one. Looks at the 100 most recent open issues.

### orchestrator/shared/agent_process.py

`agent_command`
- `cmd` as it is run for an Agent. With a `user` (limits.agent_isolation: user) it runs as that unprivileged account through sudo: the variables in `env` are passed by name, so no value shows on a command line, and a wrapper records the process group in `pidfile` so the runner (which cannot signal another user's processes) can kill it through sudo.

`run_watched`
- Run an Agent writing its event stream to `out_path`. Returns its exit status, or "timeout" after `timeout_s` of wall time, or "stall" when the stream stops growing for `stall_s` seconds (the process group is killed either way). A real run once sat 45 minutes twice with no output at all, so a silent Agent is cut off long before the overall timeout.

### orchestrator/shared/agent_runner.py

`AgentRunner.__init__`
- raises when the run's cap or time is used up; asked before every invocation
- told which credential just spent, returns the run's total so far

`AgentRunner.run`
- the runner's own home is closed to the Agent user
- the account ran dry (possibly mid-run): stop everything, do not count it as the Agent's failure
- wall time; minus llm_seconds is tool and wait time

`json_output`
- Run a role that writes a JSON file; one retry if the file is missing or malformed. `attempt(attempt_label, note)` runs the Agent and returns (exit status, cost, usage); `note` tells it what was wrong with the first try. If the Agent wrote the file under its working directory instead of the path it was given (it has done so, twice, with the right content), that copy is used. Returns (document, cost, token usage).
- read before the next attempt removes the file
- The Agent spent its whole credential and still wrote nothing usable. A second attempt gets a credential of the same size and goes the same way, so it only spends the money again (a tester did this for about $0.50 a time).
- What a failed Agent cost is spent either way; let the caller account for it.

### orchestrator/shared/agent_usage.py

`summarize_token_usage`
- Per-invocation context stats from OpenHands' persisted base_state.json.  prompt_tokens of one LLM call is that call's context size, so the max over calls is the invocation's peak context. The condenser's own calls are counted separately.

### orchestrator/shared/child_tickets.py

`module`
- where a plan's task text leaves the flag's slug; the Build Run fills in `issue-<n>` (flag_lifecycle/flag_slug.py)
- The marker's fields. `parent`: the Intake issue's number. `cs`: the change set's id in the plan. `kind`: "staging" (stage the app and verify its infrastructure; only the first child of a new app) or "update". `flag`: whether the child's change is behind a flag (the slug is `issue-<n>`). `fix_for`: set only on a fix child, the child it fixes; `fix_attempt`: which fix of that child it is (1, 2, ...). `internal_only`, `size` ("S" or "M"), `requirements`: what the planner decided. `secrets`: [{name, purpose}] the request declared. Order is not in the marker: a child's GitHub blockers are the source of truth (`ChildTickets.blockers`), because the UI shows them and readiness is judged from their state.

`ChildTickets`
- The child tickets (sub-issues) of one parent issue. `run(args, token)` runs `gh` (shared/github.run); every failure is a ChildTicketError, because a plan that half-filed its children must stop loudly instead of carrying on.

### orchestrator/shared/fake_issues.py

`FakeIssues.__init__`
- issue number -> [comment bodies]

`FakeIssues.__call__`
- after repos/<owner>/<repo>/

### orchestrator/shared/outcomes.py

`module`
- an answer to the requester, not a failure: nothing is retried, filed or learned from
- deployed dark behind a flag that does not exist, so nothing can turn it on
- The title of the failure Issue filed in the app's repo for an ending that is not good or answered.

### orchestrator/shared/provider.py

`provider_blocked_text`
- True if some line of an Agent's output is an error from the provider saying the account has no balance. Both parts are needed on one line (an error event and the billing wording), so a prompt or a log that merely mentions balances does not trip it.

`provider_check`
- A one-token request before a Build Run does any work: raises ProviderBlocked if the account has no balance, so a run cannot spend a clone, a checkout and a planner call to find out. Any other answer (including an outage) is not this condition and is left for the run to deal with.

### orchestrator/shared/rollback.py

`rollback_decision`
- (rollback, reason). Code is fixed forward, never taken out of git: nothing is reverted, and `main` keeps every commit. A change that only breaks itself is dark (its flag is never released) and a later run fixes it. The one exception is a regression, where users are exposed to broken behaviour (the tester saw, through a helper, behaviour that was live before the run stop working, or a change with no gate, no flag or an unread one, failed a check): the live app is then put back on the previous deployed version by the app's own CI (`rollback-fly.yml` redeploys that version's image), because the broken behaviour is live for everyone. The commits stay.

`rollback_deploy`
- Redeploy the previous version through the app's own CI: dispatch its `rollback-fly.yml` for the run's starting commit (whose image the earlier deploy left in Fly's registry), wait for that run, then for /api/health. Nothing is committed. Returns {"status": rolled_back|failed, "restored": sha, "deploy": healthy|deploy_failed|timeout, ...}; never raises.

### orchestrator/shared/run_stops.py

`ProviderBlocked`
- The model provider refuses every request because the account has no balance (HTTP 402). Nothing a retry, a fix request or a retrospective Agent does can help until someone tops it up, and each of them would fail the same way.

`NeedsHuman`
- kind: round_limit | time_limit | stuck | pipeline | other

`FlagMissing`
- A flag the change is gated by does not exist in GrowthBook at release, so nothing can switch the feature on. Nothing is rolled back (the feature is hidden): the story is fixed forward with a flag that exists.

### orchestrator/shared/spend_budget.py

`Budget`
- The run's one cap, enforced and metered by DeepInfra scoped JWTs.  A spending-limited JWT can carry only one model, so each Agent invocation gets its own single-model JWT limited to what is left of the run's cap. DeepInfra refuses the first call after a JWT's limit (403) and the crossing call completes. The run's spend is the sum of every JWT's spending_current, so there are still no per-Agent budgets.

`Budget.__init__`
- jwt -> last read spending_current

### orchestrator/shared/starter_template.py

`module`
- Starter Template files the coder must not change: the workflows hold the Fly token, and the flag wrapper is the release gate's other half.
- Protected files a template-sync Build Run copies from the Starter Template itself, before any Agent runs (an Agent may not edit them, and no Agent is involved). Only files that are safe to overwrite belong here: nobody but the template ever changes them.
- The Starter's lint and formatter config is owned by the Orchestrator too, so the coder cannot loosen a rule to make a check pass. A tighter rule can fail the app's existing code, so these are committed locally and pushed together with the coder's fixes (a push of the config alone would put a red Test Gate on `main`); the coder, and only the coder, fixes what the new rules report.

### orchestrator/staging/verify_infrastructure.py

`module`
- the names of the workflows the Starter's seed push runs, in order

`Deps`
- `http(method, url, headers)` -> (status, response headers as a dict with lower-case names, body text); `runs(sha)` -> the workflow runs of the app repository for that commit, [{name, status, conclusion}]; `secret_names()` -> set; `flag_connection()` says whether GrowthBook has the app's SDK connection; `sleep` and `now` are the clock.

`ci_green.settled`
- a failed stage will not recover: stop waiting

### orchestrator/try_fix/failure_text.py

`requirements`
- The retrospective Agent's own requirements are about how to fix the Factory. They belong in a Factory fix request and not in a retry of the app's request (a retry that was told to build tester helpers would go and build them).

### orchestrator/try_fix/file_bug.py

`file_bug`
- nothing runs it again until the fix merges or a person decides
- no update-app-intake yet: planning starts last
- the failed child waits for the bug Intake to close
- the PAT: this label starts planning

### orchestrator/try_fix/resume_after_merge.py

`resume`
- the PAT: the Actions token would not start the workflow

### orchestrator/try_fix/route.py

`inferred_category`
- The cause to route by. A run that ran out of money or time was too big for its limits, which is the request's problem: that decides the route unless the retrospective named a Factory cause that is not a prompt (an Agent that fails because its credential ran dry looks like a prompt gap, which it is not). With no cause named, the same rule applies.
- the change broke production: the story is retried after a fix
- the tester saw checks fail: the story is retried on its own issue, with the bugs as notes

### orchestrator/try_fix/validate_bug.py

`check`
- never the value

## Comments that used to sit in tests

What the test files said about their scenarios, by file and test.

### orchestrator/boundary_test.py

`module`
- The import rules between domains (ARCHITECTURE.md, Code layout). A domain is a folder under orchestrator/; `shared` holds what two or more domains use and imports no domain. A new edge is a deliberate edit to ALLOWED here and to the map doc. Run: python3 -m unittest discover -p "*_test.py" orchestrator
- until the planning process takes plan_change out of the Build Run (ticket 13)

### orchestrator/bugs/route_bug_test.py

`FlagStates`
- STEP 8.1, 8.2: the flag's state in the App State decides whether a story is released or dark (INV-60).

`Attach`
- STEP 8.1, 8.4: a bug is tied to a story by the flag it names, never by a guess.

### orchestrator/build_run/agent_calls_test.py

`JsonOutput.test_the_problem_is_described_for_the_agent`
- What the tester wrote in the first real watchdog test: unescaped quotes inside a string.

`JsonOutput.test_two_bad_attempts_end_in_needs_human_with_the_last_reason`
- the money both attempts spent is in the Report as a stage of its own

`JsonOutput.test_an_agent_that_spent_its_whole_credential_is_not_given_a_second_attempt`
- no "t1b"

### orchestrator/build_run/bugs_from_tester_test.py

`module`
- What the tester's failed checks become: bugs filed by the retrospective, not decided by the tester.

### orchestrator/build_run/endings_test.py

`Endings.test_a_stop_after_the_cap_is_spent_is_a_budget_ending`
- The live under-funded run: $0.0813 spent against a $0.08 cap, then the tester produced no file.

`Endings.test_a_stop_just_short_of_the_cap_is_a_budget_ending_too`
- The second live run: $0.0768 of $0.08. The tester gets half of what is left, so it runs dry before the cap itself.

### orchestrator/build_run/prepare_run_test.py

`ModelFallback.run_for`
- A BuildRun whose provider answers per model id (status, body).

`ChoosingFlagsToRetire`
- BuildRun.choose_flags_to_retire with the State issue and manifest mocked.

`NamingTheFlag.test_an_issue_that_runs_again_keeps_the_flag_it_had_and_creates_and_commits_nothing`
- A failed child resumes after its fix closes: its flag exists, off, from the earlier attempt (and may already be in flags.json).

`SuppressionsAndLintConfig.run_with_template`
- A real app checkout with a base commit, and a Starter Template folder holding `files`.

`SuppressionsAndLintConfig.test_the_lint_config_is_staged_after_the_base_and_pushed_only_with_the_coders_work`
- the staged config commit sits after the run's base, so a rollback target was deployed

### orchestrator/build_run/read_child_intake_test.py

`Identity.test_an_update_intake_needs_the_form_the_label_and_the_matching_app`
- no app: label

### orchestrator/build_run/review_code_test.py

`finding`
- A reviewer finding as the schema requires it: blocking, backed by a cited file and line.

### orchestrator/build_run/run_test.py

`finding`
- A reviewer finding as the schema requires it: blocking, backed by a cited file and line.

`RoundLoop`
- The order of a Build Run's rounds with every stage stubbed: review the local commit, push only a clean one, wait for the deploy, then test it.

`RoundLoop.make.pipeline`
- the coder's fix is now HEAD

`RoundLoop.go`
- the coder's last commit is what HEAD points at

`ReviewBeforePushThenTest`
- The reviewer reads the local commit before the push; the tester drives the deployed app after it. Agents are stubbed; git is faked.

`ReviewBeforePushThenTest.make.R`
- stands in for subprocess.CompletedProcess

`ReviewBeforePushThenTest.test_a_blocking_finding_is_returned_so_the_coder_can_fix_it_before_the_push`
- the model's own "clean" verdict is ignored

`ReviewBeforePushThenTest.test_a_failure_of_the_new_change_is_dark_only_and_one_of_released_behaviour_is_a_regression`
- the model's word alone is not enough: no helper observation, no regression; and blocked or not_run is not "broken"

`ReviewBeforePushThenTest.test_improvements_are_kept_deduplicated_and_only_the_known_kinds`
- a second sighting adds nothing

### orchestrator/build_run/ship_code_test.py

`Diagnosis`
- STEP 4.8: a failed pipeline step is read by the Pipeline Agent, whose category decides: a flaky or infrastructure failure is re-run (up to `pipeline_retries`), a failure in the code goes back to the coder (up to `pipeline_fix_attempts`), anything else stops for a person.

### orchestrator/build_run/start_build_test.py

`PlannedChildrenOnly.start`
- `parent` is {number, state} (or None) for the child's parent, answered by the sub-issues API.

### orchestrator/build_run/track_progress_test.py

`finding`
- A reviewer finding as the schema requires it: blocking, backed by a cited file and line.

### orchestrator/build_run/ui_check_test.py

`Handler.do_GET`
- a page that fills in after a network-sized delay

### orchestrator/build_run/verify_deployed_app_test.py

`VerificationStates.test_a_check_whose_own_evidence_admits_it_was_not_observed_does_not_pass`
- The first real run on an unobservable requirement: marked passed, evidence said it could not be seen.

### orchestrator/build_run/write_code_test.py

`CheckProblem`
- The Orchestrator's own `npm run check` on the coder's commit, before the reviewer.

### orchestrator/flag_lifecycle/lifecycle_test.py

`module`
- One flag through STEP 5.1 to 5.7, with an in-memory GrowthBook: dark, released, eligible, retired; switched off by the watchdog and released again; and the dark feature a person approves for removal.

`OneFlagThroughItsLife.start`
- 5.1: created off before the coder starts

`OneFlagThroughItsLife.test_5_1_to_5_4_dark_then_released_then_eligible_then_retired`
- 5.2
- 5.4: the coder is told, the verifier holds it to it

`OneFlagThroughItsLife.test_5_2_to_5_5_to_5_2_the_watchdog_switches_it_off_and_the_fix_releases_the_same_flag`
- a run that does not own the flag leaves it alone
- the story's own run switches the same flag back on

`OneFlagThroughItsLife.test_5_5_to_5_7_a_dark_feature_a_person_approves_is_removed_as_a_flagless_change`
- 5.6: the owner added approve-retire
- 5.7: one request, no new flag, delete the check, the code, the tests and the line

### orchestrator/flag_lifecycle/watchdog_test.py

`Disabling.test_each_flag_is_switched_off_and_read_back_and_one_that_stays_on_is_reported.stubborn`
- accepted, but nothing changed

### orchestrator/flow_spec_test.py

`module`
- Keeps docs/flow-spec.md honest: the diagram and the step index list the same unique step IDs, every edge points at a defined step, and every STEP n.m cited in the docs, and every Step in the invariants table, exists. Run: python3 -m unittest discover -p "*_test.py" orchestrator

`expand`
- "5.1-5.7" is the range 5.1 .. 5.7; "4.3" is one step.

`diagram_steps`
- Every step node is declared as S<group>_<n>["<b>group.n Title ..."] (or a { } / ( ) shape) and its label starts with its own ID.

### orchestrator/invariants_test.py

`module`
- One test per design invariant in docs/invariants.md. Run: python3 -m unittest discover -p "*_test.py" orchestrator  The meta test at the bottom keeps the table and these tests in step: every INV-NN row has exactly one `test_invNN_...` here and every test here has a row.

`Invariants.test_inv04_the_verdict_comes_from_the_findings_and_their_structure`
- a blocking label does not block unless its fields back it: an opinion, or a category that cannot block, is minor
- no structure at all: the reviewer is asked again, a label is not trusted

`Invariants.test_inv23_a_change_set_starts_only_after_its_blockers_close_and_only_once`
- one at a time: a second ready change set waits, nothing starts while one is in flight, and a stalled child holds the others

`Invariants.test_inv25_nothing_is_reverted_in_git_and_only_a_regression_rolls_the_deploy_back_through_ci`
- the Orchestrator has no way to revert: no function, and the rollback runs the app's own workflow and touches no git

`Invariants.test_inv26_a_child_that_ends_badly_and_every_other_failure_event_is_judged_and_handled_once`
- a release the watchdog switched off is the story's to fix

`Invariants.test_inv39_a_fix_is_one_ordinary_child_that_the_failed_child_waits_for`
- the planner's flag decision stands: a fix child is an ordinary child

`Invariants.test_inv42_only_reviewed_code_is_pushed_and_the_reviewer_runs_before_the_push`
- and the run's rounds, exercised end to end with the stages stubbed (build_run_test.RoundLoop)

`Invariants.test_inv43_a_dark_feature_is_removed_only_after_the_retries_and_a_persons_approval`
- while retries remain, or when nothing is dark-broken, the label does nothing

`Invariants.test_inv44_the_tester_says_what_a_failure_means_and_only_what_a_helper_saw_is_a_regression`
- the model's word alone is not a regression

`Invariants.test_inv45_the_retrospective_agent_is_isolated_like_the_build_run_agents`
- the tests of the proposal never run in the Orchestrator's own environment

`Invariants.test_inv47_the_lint_config_is_the_orchestrators_and_a_stricter_rule_never_reaches_main_alone`
- staged after the run's base and never pushed on its own: the base is recorded before the config is staged

`Invariants.test_inv48_a_request_needing_a_secret_builds_nothing_until_its_names_exist`
- all present: the build may go on
- every later start checks the recorded names before any Agent is paid for: a retry, a re-run, a child issue

`Invariants.test_inv49_a_commit_with_a_secret_value_or_an_undeclared_name_is_never_pushed`
- a name the app already had at the run's base was accepted before: a later run that does not touch it is not rejected for it

`Invariants.test_inv51_a_flags_name_is_issue_n_of_its_story_and_it_exists_off_before_the_coder_starts`
- the plan only says "flagged"; the slug is filled in per issue

`Invariants.test_inv57_a_staging_child_is_verified_by_deterministic_checks_before_anything_is_built_on_it`
- only a staging child is staged

`Invariants.test_inv58_every_failure_event_gets_a_verdict_a_failure_is_never_downgraded_and_a_warning_needs_a_reason`
- "fix" without a reason is not a fix

### orchestrator/maintenance/template_sync_test.py

`Changes.test_protected_and_lock_files_are_not_applied`
- the lint config is the Orchestrator's, not the coder's

### orchestrator/monitoring/benchmark_test.py

`Suite.test_the_shipped_suite_is_valid_and_its_oracles_are_real_api_checks`
- the same file format the tester's helper reads

`Planned.test_the_planners_cost_is_read_from_the_ledger_by_its_run_id`
- a Build Run's own line is not a planning cost

`Planned.test_the_seed_flag_is_filled_into_a_request_and_the_estimate_counts_a_refusal_as_planning_only`
- the planner is in every task's price

### orchestrator/planning/file_children_test.py

`FilingChildren.test_a_fix_child_is_an_ordinary_child_that_keeps_the_planners_flag_decision_and_records_what_it_fixes`
- the child names no one else's flag, and the chain is counted from the failed child

### orchestrator/planning/render_child_test.py

`ChangeSets.test_a_flagged_change_set_leaves_the_slug_for_the_run_to_fill_in_and_the_comment_says_so`
- an older plan's own slug is kept

### orchestrator/planning/validate_plan_test.py

`Plan.test_a_flagged_change_set_may_just_say_true_and_the_orchestrator_names_the_flag`
- two flagged sets do not "share" a flag: each is named after its own issue
- no flag and not internal is still a problem

`Plan.test_retiring_a_flag_is_internal_and_must_not_be_given_a_new_flag`
- From the first real retirement runs: the planner invented a flag to retire a flag.

`Plan.test_the_recorded_planner_mistakes_are_caught_and_their_good_versions_pass`
- agents/planner-fixtures/cases.json: plans shaped like the real mistakes in the factory-learning issues.

`RollbackSized.test_the_staging_change_set_needs_no_requirement_link_but_a_business_one_still_does`
- found by the first live planning: the staging change set has no business logic, so the planner rightly links it to nothing

### orchestrator/provider_blocked_test.py

`module`
- A model provider that refuses every request because the account has no balance (found when DeepInfra answered 402 mid-session). Nothing retries, files a self-starting fix request or runs a retrospective Agent for it; one alert asks for a top-up.
- The event OpenHands printed, taken from the real log.

`Detection.test_scanning_an_agent_file_looks_only_at_its_end_and_survives_a_missing_file`
- an old error followed by plenty of normal output

`Places.test_other_answers_are_not_this_condition`
- does not raise

### orchestrator/refusal_test.py

`module`
- A refusal is an ending of its own: not a failure to retry or learn from (planning/triage.py decides it; the Build Run and the retrospective treat it).

### orchestrator/retrospective/agent_run_test.py

`Isolation`
- The retrospective Agent runs in a copy of the tree as the Agent user, and only allowed files come back.

### orchestrator/retrospective/app_state_test.py

`AppState.test_a_dark_feature_is_listed_but_is_never_taken_for_a_released_flag_and_a_later_release_replaces_it`
- not "released": nothing retires it
- never built: no dark feature remains

### orchestrator/retrospective/close_child_test.py

`ReadyToStart.test_a_stalled_child_blocks_its_siblings_until_it_is_retried_or_closed`
- it lost `proceed-with-change` when its run stopped, and it is not waiting any more: nothing else may start behind it
- retried: in flight again

`Advance.test_a_child_whose_blocker_is_still_open_does_not_start`
- also blocked by a later, still open child

`Advance.test_a_failed_child_blocks_the_ones_after_it`
- b was started and its run stopped: it lost the go label, so c may not start even though a is closed

`SettleFix`
- Plan 5 has the failed child 12 (waiting, blocked by the bug Intake 50) and a sibling 13; the bug Intake 50 has its one fix child 51.

`SettleFix.test_when_the_bug_intake_closes_the_story_hears_it_and_the_failed_child_starts_again_not_its_sibling`
- the fix child was the Intake's last child

`SettleFix.test_a_fix_that_itself_needed_a_fix_resumes_each_failed_child_in_turn_up_the_chain`
- Fix child 51 (under bug Intake 50) failed and waits for bug Intake 60, whose fix child is 61: closing 61 restarts 51, and 51 closing restarts 12.

### orchestrator/retrospective/finalize_test.py

`module`
- The finalize step end to end for a failed run: a real git repo, gh mocked.

`Run`
- A run that pushed one commit on top of its base.

`Finalize.test_a_regression_rolls_the_deploy_back_through_ci_before_anything_is_reported`
- the retrospective reads state.json, so the rollback and the audit must be saved there

### orchestrator/retrospective/improvement_issues_test.py

`Improvements.run_main`
- main() with gh mocked; returns the gh calls.

`Improvements.test_each_improvement_goes_to_its_own_tracker_and_only_the_factory_one_is_for_the_agent`
- nothing is filed in the app's repo: the Retrospective judges that event

### orchestrator/retrospective/learning_pr_test.py

`MergePolicy.test_a_smoke_fixture_must_be_a_diff_with_an_expected_entry`
- What the first learning PR did: files in the fixtures folder that the harness never runs.

`Guardrails.test_shouting_in_added_prompt_lines_is_caught_wherever_it_appears`
- Lines taken from the first two learning PRs.

### orchestrator/retrospective/story_report_test.py

`Bugs.test_a_failed_run_notes_its_bugs_on_the_story_unless_a_bug_intake_already_carries_them`
- the bug Intake's requirements carry them already

### orchestrator/shared/agent_runner_test.py

`JsonOutput.attempts`
- An `attempt` that writes the next entry of `writes` (None = write nothing) and costs 0.1.

### orchestrator/shared/api_check_test.py

`Handler.do_POST`
- 200, not 201: a seeded bug

### orchestrator/shared/outcomes_test.py

`Outcomes.test_no_other_module_keeps_its_own_copy_of_the_good_endings`
- Four modules used to mirror this tuple, and a test kept them in step (INV-24).

### orchestrator/shared/prompts_test.py

`Prompts`
- Every role prompt's placeholders are exactly the ones the orchestrator supplies.

### orchestrator/shared/rollback_test.py

`module`
- Rolling the deploy back after a regression: through the app's own CI, never by reverting commits in git.

`run_state`
- The Report of a run that pushed one commit on top of base.

`Sh`
- A stand-in for `sh` that answers `gh run list` from a script and records every command.

### orchestrator/shared/spend_budget_test.py

`BudgetAccounting.test_spend_sums_across_jwts_and_exhaustion_stops_minting`
- the crossing call completes, so overshoot is allowed

### orchestrator/smoke_tester_test.py

`module`
- The pure logic of agents/smoke-tester/run.py: how a bug is seeded and how a tester report is judged.

`Seeding.test_an_edit_that_does_not_apply_is_an_error_not_a_silent_correct_app`
- ambiguous

`Judging.test_the_reason_patterns_do_not_match_unrelated_digits_or_words`
- id-zero used "0|zero|...", which matched the 0 in "200"; dup-ids used "...|id", which matched every message.

`Judging.test_a_check_that_admits_it_was_not_observed_does_not_count_as_a_pass`
- the integrity rule: this is how the unobservable requirement was wrongly released once

`Judging.test_a_tester_that_could_not_run_anything_is_inconclusive_not_a_catch`
- Seen live: every check not_run ("unable to execute curl"). The release gate refuses it, but it found no bug.
- one real failure alongside not_run checks is a real catch
- the unobservable fixture expects "not passed", and not_run is exactly the honest answer there

### orchestrator/staging/route_child_test.py

`RouteTheChildByKind`
- STEP 2.6: a child with `proceed-with-change` goes to App Staging when its marker says `kind: staging` and to a Build Run otherwise, never to both. The workflows decide with a text match on the body, so the match is checked against the marker the planner actually writes.

### orchestrator/staging/stage_script_test.py

`module`
- infra/app-staging/stage.sh in its dry-run mode, with a fake `gh` first on the PATH: the child is read and checked, what would be staged is printed, and nothing is created (no Fly, GrowthBook, repository or secret call is made; only reads and, on a refusal, a comment).

### orchestrator/staging/verify_infrastructure_test.py

`FakeApp`
- A deployed Starter app as far as the checks can see it: health, the front page, the preview cookie, and whether GrowthBook has its connection.

### orchestrator/starter_lint_test.py

`module`
- The Starter Template's custom lint rules, run against the cases in agents/lint-fixtures/cases.json with the real ESLint.

### orchestrator/try_fix/file_bug_test.py

`Filing.test_a_dark_story_gets_a_bug_intake_with_the_fix_for_marker_and_the_failed_child_waits_for_it`
- the failed child's own instructions travel with the fix

`Filing.test_the_story_hears_about_the_failure_and_the_bug_once`
- a second event on the same story

### orchestrator/try_fix/render_bug_test.py

`Bug`
- Contract with real GitHub, checked read-only on 2026-10-20: `gh issue list --search "[<8 hex>] in:title"` found the one issue whose title carries that bracketed key (ai-factory#136, #133), so the bracketed key is findable by file_bug.open_bug.
