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

# Fast loop while editing (use these between changes, not the full build):
npm run check                  # type-check both workspaces and lint (ESLint), no bundle, seconds
npm run format                 # Prettier rewrites the files; run it before you commit (the style guide is the formatter)
npm run test:changed           # only tests affected by files changed since the last commit
npm run test:file -- src/__tests__/health.test.ts   # one test file (path relative to backend/)
npm run verify                 # check + full test, without the Vite bundle
```

The Test Gate requires unit tests for
business logic plus one boot/health-check smoke test — see
`backend/src/__tests__/health.test.ts` for the smoke-test pattern to extend.

## Feature flags

- `backend/src/feature-flags.ts` holds the single OpenFeature client,
  initialized once at startup (`index.ts`, before `app.listen()`) — never
  re-derived per request.
- When flags apply: every change goes behind a flag of its own, to protect
  `main`, unless the task says it needs none. One flag covers the whole
  change, not each route or screen. The task gives the flag's slug.
- Flag-key convention: `<app-slug>.feature.<slug>` (e.g. `my-app.feature.todos-crud`).
  The app slug is derived at runtime (`appSlug()`; Fly's `FLY_APP_NAME`, or
  `APP_SLUG` locally) — never hardcode it. Use `featureKey(slug)` /
  `isFeatureEnabled(res, slug)` from `feature-flags.ts` at every call site,
  never raw key strings, so Preview works uniformly.
- **Record every new flag in `flags.json`** (repo root, an array of
  `{"slug": "todos-crud", "description": "..."}`) in the same commit that
  adds it in code. The Orchestrator reads this to create and release flags
  after review; an unrecorded flag never gets released. A flagged change
  ships dark: it must stay behind its flag until the Orchestrator releases it.
- **Test every flag both ways.** For each flag in `flags.json`, write one
  test inside `withFlag("<slug>", false, ...)` (the old behaviour is
  unchanged) and one inside `withFlag("<slug>", true, ...)` (the new
  behaviour), using `withFlag` from `backend/src/__tests__/with-flag.ts`, and
  check the flag in one place only. `npm run check` fails when either test is
  missing or the flag is checked more than once.
- Preview: requests carrying `PREVIEW_TOKEN` (header `X-Preview-Token`, or
  `?preview=`) see every feature flag as on, so reviewers can test dark
  features. This is wired in `feature-flags.ts`; don't build another bypass.
- Every call site passes `false` as the default of a boolean flag, never
  `true`: GrowthBook's "off" reads as the default, so a `true` default makes
  the flag impossible to turn off. A flag therefore fails closed if GrowthBook
  is unreachable.
- `GROWTHBOOK_CLIENT_KEY` (required) is the per-Managed-App SDK
  connection key, and `PREVIEW_TOKEN` the preview secret; both are pushed as
  repo secrets by the Orchestrator.

## Rules

- **Config and secrets.** Environment variables only, nothing hardcoded; document every variable in the committed `.env.example`. A secret the task names is already in `process.env.<NAME>`: list its name and purpose in `secrets.json`, and never write a value anywhere (code, tests, logs).
- **Dependencies.** Use an existing dependency before adding one. Prefer free, open-source, self-hostable packages; no paid SaaS SDK unless the task requires one.
- **Stored data is additive.** A flag hides code, not data, and switching it off cannot undo a write. Add a field, table or index and keep reading and writing the old shape; never drop, rename or retype something the previous version still reads in the same change. A migration must be safe to run twice.
- **Logging and errors.** Structured JSON logs to stdout. A global `uncaughtException` and `unhandledRejection` handler logs the full stack before the process exits; never crash silently.
- **Git.** Commit to your local `main`, staging only the files you meant to change. Never push, never rewrite history.
- **Not yours.** `.github/`, `Dockerfile`, `fly.toml`, `fly/`, the lint and formatter config and `backend/src/feature-flags.ts` belong to the Starter Template; commits that change them are discarded.
