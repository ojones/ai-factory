---
title: Reuse the environment across rounds
type: grilling
status: closed
assignee: ojones
blocked_by: [01-measure-where-time-goes]
---

## Question

Does each coder round start with a cold npm install? If measurement shows it, should we reuse the checkout/node_modules between rounds or cache dependencies, and where does that live (orchestrator vs template)?

## Resolution

- **The premise was half wrong.** The Managed App is cloned once into `app_dir` and every coder round reuses that checkout; `restore_tree`'s `git clean -fdq` (no `-x`) leaves ignored `node_modules` and `dist` alone. Rounds 2+ do not reinstall. The tester uses a worktree but tests over HTTP, so it needs no install.
- **What was left:** round 1's install happened as coder agent turns. Now `install_dependencies` in `orchestrator/build_run.py` runs `npm ci` once right after the clone, before the coder starts, with the coder's minimal environment so install scripts never see the runner's secrets. It skips without a lockfile, logs its duration, and a failure is only logged (the coder can still install). Tests added; 40 pass. The coder prompt says the Orchestrator already ran `npm ci`.
- **Not done:** an npm download cache on the runner. `setup-node`'s cache keys on a lockfile in the workspace, and the app is cloned later, so it would need a manual `actions/cache` step on `~/.npm`; worth it only if the logged `npm ci` time turns out to be large.
