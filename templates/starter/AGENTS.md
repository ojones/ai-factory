# AGENTS.md

This file is auto-loaded into the Agent's system prompt (OpenHands natively
reads `AGENTS.md` at the repo root). It's seeded by the Factory's Starter
Template — extend it with project-specific notes as this Managed App
grows; a rules file nobody updates goes stale.

## Stack

- Backend: Express, TypeScript, compiled with `tsc`.
- Frontend: React, TypeScript, built with Vite to static assets.
- One Node.js codebase, two npm workspaces (`backend/`, `frontend/`) under a
  single root `package.json`.
- The backend serves the frontend's built assets itself via
  `express.static()` — one container, no separate frontend server.

## Structure

```
backend/   Express app (src/app.ts builds it, src/index.ts boots it)
frontend/  React app (Vite)
Dockerfile Multi-stage build — compiles both, runtime stage just runs node
```

## How to run

```bash
npm install                    # installs both workspaces (npm workspaces)

# Local development (two processes, two ports; Vite proxies /api to the backend):
npm run dev:backend            # backend on PORT (default 3000), with reload
npm run dev:frontend           # Vite dev server with HMR

# Production-shaped build + run (what the Dockerfile does):
npm run build                  # builds frontend, then backend
npm start                      # serves everything on one port (PORT, default 3000)
```

## How to test

```bash
npm test                       # runs the backend's vitest suite
```

The test gate (per root STANDARDS-CODING.md) requires unit tests for
business logic plus one boot/health-check smoke test — see
`backend/src/__tests__/health.test.ts` for the smoke-test pattern to extend.

## Feature flags

- `backend/src/feature-flags.ts` holds the single OpenFeature client,
  initialized once at startup (`index.ts`, before `app.listen()`) — never
  re-derived per request.
- Flag-key convention: every new user-facing feature/behavior change gets
  its own flag, keyed `feature.<slug>` (e.g. `feature.todos-crud`). The
  mandatory global kill switch uses the fixed key `global-kill-switch`
  (see `GLOBAL_KILL_SWITCH_KEY` in `feature-flags.ts`) — already wired into
  top-level middleware in `app.ts`, mounted after the health route (so
  health checks keep working in maintenance mode) and before everything
  else.
- Every call site must pass a real default value to `getBooleanValue()` (or
  the equivalent for other types) — that default is what OpenFeature falls
  back to if the GrowthBook instance is ever unreachable, per
  STANDARDS-FEATURE-FLAGS.md's resilience rule.
- `GROWTHBOOK_CLIENT_KEY` (required) is the per-Managed-App SDK
  connection key, pushed as a repo secret by the Orchestrator.

## Rules

This is a scaffold, not the full rulebook. Full Standards (style, git
workflow, secrets/config, dependency policy, deployment, logging/error
handling, feature flags) live at the root of the `ai-factory` repo this
template was seeded from:

- `STANDARDS.md` (index)
- `STANDARDS-CODING.md`
- `STANDARDS-DEPLOYMENT.md`
- `STANDARDS-VISIBILITY.md`
- `STANDARDS-FEATURE-FLAGS.md`

If this repo was seeded into a new Managed App, those files may not
be physically present here — treat this section as a pointer back to the
Factory's canonical copies.
