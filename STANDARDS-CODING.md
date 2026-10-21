# Coding Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology.

## Stack

Every Managed App is **Express (backend) + React (frontend), both in TypeScript** — one Node.js codebase, frontend built via Vite to static assets served directly by Express's `express.static()`. Not re-derived per project: only JS/TS pairs a competitive backend framework with a genuine frontend-framework ecosystem, and Express/React are each their ecosystem's dominant, most battle-tested choice. Runner-up: FastAPI (Python) + React — loses on forcing a second language into every Managed App.
→ [issues/20](.scratch/orchestrator-spec/issues/20-which-application-stack.md)

## Starter Template

Every new Managed App is seeded from a fixed **Starter Template** (directory structure, CI config, boilerplate) rather than built from scratch each Build Run — cheaper in agent tokens, keeps every Managed App structurally identical.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Rule discovery

`AGENTS.md` at the repo root — OpenHands natively auto-loads this into its system prompt. The Starter Template seeds its base content (stack, structure, how to run tests/build, pointers to these Standards); Agents extend it with project-specific notes as the Managed App grows.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Test gate

A hard gate in the deployment pipeline, not Agent judgment: unit tests for business logic, plus one minimal boot/health-check smoke test. No coverage-percentage threshold.

If the gate fails after a push, the same Build Run keeps watching the GitHub Actions run (a Pipeline Agent diagnoses, the coder fixes — see [ARCHITECTURE.md](ARCHITECTURE.md#agents-and-build-run-stages)) until green, bounded by the cost guardrail ([ARCHITECTURE.md](ARCHITECTURE.md#cost-guardrails)) — never a fire-and-forget push that can leave `main` broken indefinitely.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Style

Purely mechanical — checks are the style guide, not prose. The Starter Template ships Prettier (`npm run format`) and ESLint (`npm run lint`, part of `npm run check` and so of the Test Gate); formatting itself is not a gate, so an old file is never failed for its layout, but the coder runs `npm run format` first, before the build and the tests. No prose conventions (naming philosophy, comment density) for an Agent to probabilistically get wrong. Beyond formatting, the lint config carries the Factory's own rules for what recurring review findings showed (a test must not assert on source text or on `flags.json`, no committed `.only`, a test must make an assertion, and one whose only assertions are `toBeTruthy`/`toBeDefined` is a warning; anything named `expect*`, `assert*`, `verify*` or `should*` counts as an assertion, so a helper such as `expectStatus` is fine); each has failing and passing cases in `agents/lint-fixtures/cases.json`. The lint and formatter config belongs to the Orchestrator: the coder cannot edit it or suppress a rule to get past it, it fixes the code. New rules arrive through template sync and the coder fixes what they report in that Update App Intake.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Factory Python

The Factory's own Python (`orchestrator/`, `agents/`) is linted with [ruff](https://docs.astral.sh/ruff/), configured in `pyproject.toml` (`ruff check`, a step of the `unit` job in `factory-checks.yml`). Rules are added there one at a time, so the set only grows.

- **Test files** are named `<name>_test.py`, beside the module they test (`build_run/run.py` → `build_run/run_test.py`), never `test_<name>.py`. CI runs `python -m unittest discover -p "*_test.py" orchestrator`, which only finds that suffix, so a misnamed file would silently never run. Test methods inside a file keep the `test_` prefix, which `unittest` requires.
- **Functions are short.** Aim for 5 lines or fewer, 10 is fine, and over 10 fails the build. A line count runs from a body's first statement to its last. If a function wants a comment to explain a step, extract that step into a function whose name says it.
- **Comments are avoided.** Name things so a comment is superfluous. No docstrings, no bare string standing in for a comment, and code must not read `__doc__`. `# noqa`, `# type:`, `# pragma` and a shebang are allowed. Triple-quoted strings are fine as data (a prompt, a fixture), just not as a statement on their own.

- **The dignified-Python rules** ([docs/dignified-python-core.md](docs/dignified-python-core.md)). Ruff enforces pathlib over `os.path` (`PTH`), absolute imports (`TID252`), imports at module level (`PLC0415`; a deliberate lazy import carries `# noqa: PLC0415`), an explicit encoding on every file read and write (`PLW1514`), no useless re-export aliases (`PLC0414`), and no `try`/`except`/`pass` (`S110`, `SIM105`). `style_test.py` enforces the indentation limit. Look before you leap applies wherever a check can replace the exception; exceptions stay at boundaries a check cannot cover (parsing JSON or dates, the network, subprocesses, and the run-ending exceptions in `run_stops` and `endings`). The rest (O(1) properties, no backwards-compatibility shims, variables declared next to their use, no single-use destructuring) are followed by convention; no tool checks them.

`orchestrator/style_test.py` enforces all of it (ruff has no rule for these) and fails the build. The numbers (`GOAL_LINES`, `MAX_LINES`, the allowed comment markers) are constants at its top. Code written before these rules is listed in `orchestrator/style_baseline.json`: a listed function may not grow, a file may not gain comments, and nothing new may be over the limit. When you shorten a function or drop comments the test asks you to tighten the baseline: `python3 orchestrator/style_test.py --update`. `--report` prints how far the codebase is from the goal.

## Git workflow

Only the coder Agent pushes, and it pushes directly to `main` — no branches, no PRs. Review happens after the push, on `main`, while the new feature is still dark behind its feature flag ([STANDARDS-FEATURE-FLAGS.md](STANDARDS-FEATURE-FLAGS.md#release-and-retirement)). The flag is the gate for going public, the test gate is the gate for a healthy build, and a self-merged PR would add a step without adding safety.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Data and migrations

A feature flag hides code, not data. A deploy applies any change to stored data to every user at once, while the feature is still dark, and switching the flag off cannot undo it. So a change that touches how data is stored is **additive**: add a new field, table or index and keep writing and reading the old shape until the new code has been released and is permanent. Never drop, rename or retype something the previous version still reads in the same change; do that in a later, separate update (expand, then contract) once nothing reads the old shape. A migration must be safe to run twice and must leave the previous version of the app working. The reviewer treats a non-additive change to stored data as blocking.

## Secrets and configuration

All runtime config/secrets via env vars only, documented via a committed `.env.example`. Zero hardcoded values.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Dependencies

Default to free/OSS/self-hostable packages; avoid paid SaaS SDKs unless a task genuinely requires one.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Commit messages

No mandated format. Nothing in this spec reads commit messages programmatically, and there's no human changelog audience.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)
