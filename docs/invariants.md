# Design invariants

The "must" rules of the Orchestrator and Starter Template, each with an ID. Every row has a test in [orchestrator/test_invariants.py](../orchestrator/test_invariants.py), named `test_invNN_...`, and a test checks that this table and the test file list exactly the same IDs, so a rule cannot be added here without a test or dropped from the tests silently. The reasoning for each rule is in [ARCHITECTURE.md](../ARCHITECTURE.md) and the [Standards](../STANDARDS.md).

Some tests exercise the code (what the rule says must happen), some read a file (the rule is a property of a workflow, a template or the docs), and some compare the docs with `agents/profiles.yml` so that the two cannot drift apart. [audit.py](../orchestrator/audit.py) checks the same kind of rule against what a real Build Run actually did.

| ID | Rule | Source |
|---|---|---|
| INV-01 | An Agent runs with a whitelisted environment: its own credential and role inputs, never the PAT, the Fly token, the GrowthBook admin key or the DeepInfra parent key. | ARCHITECTURE: Credentials |
| INV-02 | A coder commit that touches a protected file (`.github/`, `fly.toml`, `fly/`, the flag wrapper, `INTAKE.md`) is rejected. | ARCHITECTURE: Agents and Build Run stages |
| INV-03 | A release happens only when CI is green, the deploy is healthy, the tester passed and the reviewer is clean, all for the same SHA. | ARCHITECTURE: stage 4 |
| INV-04 | The reviewer's verdict is derived from its findings; the model's own `verdict` field is ignored. | ARCHITECTURE: Reviewer |
| INV-05 | A tester check passes only in the state `passed`; `failed`, `blocked` and `not_run` all keep a change from releasing. | ARCHITECTURE: Tester |
| INV-06 | The release step never re-enables or alters a flag that already exists in GrowthBook. | ARCHITECTURE: stage 4 |
| INV-07 | The watchdog switches off only the flags its own run released. | ARCHITECTURE: stage 4 |
| INV-08 | The Preview Token the Build Run computes is the one the shell script computes for App Staging. | ARCHITECTURE: Secrets pushed |
| INV-09 | Each Agent invocation's credential is a single-model scoped JWT limited to what is left of the run's cap. | ARCHITECTURE: Cost guardrails |
| INV-10 | An Intake cost-cap override above the configured ceiling, or not above zero, is refused. | ARCHITECTURE: Cost guardrails |
| INV-11 | The review-round limit stated in ARCHITECTURE.md is the one in `agents/profiles.yml`. | docs match config |
| INV-12 | The coder and reviewer models named in ARCHITECTURE.md are the ones in `agents/profiles.yml`. | docs match config |
| INV-13 | Every role prompt named in `agents/profiles.yml` exists in the Factory repo, which Managed App repos never contain. | ARCHITECTURE: Agents |
| INV-14 | The post-mortem Agent can change only prompts, the Starter Template, the orchestrator and the docs, never workflows or protected template files. | ARCHITECTURE: Learning loop |
| INV-15 | A learning PR auto-merges only when it is an additive change to lint or formatter config. | ARCHITECTURE: Learning loop |
| INV-16 | The Starter Template's flags fail closed: no flag is read with a default of `true`, and the kill switch sits after the health route and before the static files and every other route. | STANDARDS-VISIBILITY, STANDARDS-FEATURE-FLAGS |
| INV-17 | The Summary, Report and failure Issue are written even after a crash, breach or cancel: `finalize` and the post-mortem step run `if: always()`. | ARCHITECTURE: Visibility |
| INV-18 | Build Runs of one app never overlap and a running one is never cancelled: the Build Run workflow's concurrency group is per app with `cancel-in-progress: false`. (A second queued run can still replace an older pending one; that is a known gap, open ticket 02.) | ARCHITECTURE: Intake |
| INV-19 | A run whose rounds leave the same checks failing and the same findings open stops instead of spending its remaining budget. | ARCHITECTURE: stage 5 |
| INV-20 | The post-mortem Agent never receives the DeepInfra parent key; it gets a capped scoped credential or does not run. | ARCHITECTURE: Learning loop |
| INV-21 | Every workflow that installs OpenHands pins it to the version in `agents/openhands-version.txt`, so an upstream release cannot change an unattended run. | ARCHITECTURE: Visibility |
| INV-22 | An Update Intake can change only a repo this Factory created (its description carries the `Intake: <factory repo>#<n>` marker); anything else is refused and nothing is dispatched. | ARCHITECTURE: Intake |
| INV-23 | A change set of a plan starts only when every change set it depends on is closed, and only one starts at a time, so an app never has two pending Build Runs (GitHub would drop one). | ARCHITECTURE: Intake |
| INV-24 | `update-intake.yml` starts a Build Run only when the label `proceed-with-change` is added to an `update-intake` issue, and every module agrees on which outcomes are good endings. | ARCHITECTURE: Intake |
