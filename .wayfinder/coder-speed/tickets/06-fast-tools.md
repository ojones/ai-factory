---
title: Give the coder fast tools
type: grilling
status: closed
assignee: ojones
blocked_by: []
---

## Question

What tools would cut exploration: a single 'run affected tests' command, symbol search or grep instead of whole-file reads? Which are worth adding to the Agent harness?

## Resolution

The coder has only OpenHands' terminal and editor, so the fast tools are npm scripts in the Starter Template, documented in its `AGENTS.md`:

- `npm run check`: `tsc --noEmit` in both workspaces, no Vite bundle.
- `npm run test:changed`: `vitest run --changed`.
- `npm run test:file -- <path>`: one test file, path relative to `backend/`.
- `npm run verify`: check plus full test.

The coder prompt uses them when `AGENTS.md` lists them and falls back to the old commands otherwise. Existing Managed Apps are not backfilled (decision: new apps only). Checked in a clean copy of the template with `npm ci`; the working tree's own `node_modules` has a broken vite install, which fails `npm test` with or without these changes. Check takes about 1s on the tiny starter, so the real gain shows on larger apps; "grep and symbol search" was dropped because the terminal already has grep.
