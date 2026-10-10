---
title: Make template build and test faster
type: grilling
status: closed
assignee: ojones
blocked_by: [01-measure-where-time-goes]
---

## Question

Options: incremental TypeScript builds, test sharding, skipping the full build in intermediate rounds with the Orchestrator still running the full set before push. Which are safe in the Starter Template?

## Resolution

The slow part of each round is the Test Gate -> Build -> Deploy chain, three workflows each paying runner startup, with `npm ci` and the full build done twice and no Docker layer cache. Changes to the Starter Template (new apps only), with `STANDARDS-DEPLOYMENT.md` and `ARCHITECTURE.md` updated to match:

- **Docker layer cache** in `build.yml` (`cache-from`/`cache-to` type=gha).
- **Test Gate** drops the duplicate full build and runs `npm run check` instead (install, type-check, tests).
- **Test Gate and Build run in parallel** on push to main. `deploy-fly.yml` triggers on either finishing, and a `gate` job lets only the run that sees both green for the SHA deploy (concurrency per SHA). `latest` moved from Build to Deploy so it only follows commits that passed both.
- **Orchestrator:** `wait_run` now ignores Deploy runs whose deploy job was skipped, since the first completion's run reports success without deploying (otherwise the health check could pass against the old version). Tests added; 42 pass.

Not done: the GHCR -> Fly re-push (Standards requirement, left alone). Unverified: the workflows were validated as YAML only, not run on GitHub; the `gh run list --jq` gate script and the first real push to a new app are the things to watch. A build-only failure (Vite bundle) now surfaces in Build instead of Test Gate, which the Pipeline Agent handles the same way.
