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

Purely mechanical — an auto-formatter is the entire style guide. No prose conventions (naming philosophy, comment density) for an Agent to probabilistically get wrong.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Git workflow

Only the coder Agent pushes, and it pushes directly to `main` — no branches, no PRs. Review happens after the push, on `main`, while the new feature is still dark behind its feature flag ([STANDARDS-FEATURE-FLAGS.md](STANDARDS-FEATURE-FLAGS.md#release-and-retirement)). The flag is the gate for going public, the test gate is the gate for a healthy build, and a self-merged PR would add a step without adding safety.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Secrets and configuration

All runtime config/secrets via env vars only, documented via a committed `.env.example`. Zero hardcoded values.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Dependencies

Default to free/OSS/self-hostable packages; avoid paid SaaS SDKs unless a task genuinely requires one.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)

## Commit messages

No mandated format. Nothing in this spec reads commit messages programmatically, and there's no human changelog audience.
→ [issues/11](.scratch/orchestrator-spec/issues/11-coding-standards-content.md)
