Type: research
Status: resolved

## Question

Given deployment Standards should pin one default hosting target while keeping it swappable per project (see [Deploy target decision](04-deploy-target-default-swappable.md)), which target should be the default for Built Applications (backend+frontend, containerized, deployed via GitHub)?

Compare candidates (e.g. Fly.io, Railway, Render, a bare VPS running Docker Compose, AWS ECS Fargate, and any other cheap container-hosting option) against:
- Cost at small scale (a handful of low-traffic apps)
- Friction of a Docker image + GitHub Actions deploy flow
- How easily a given Built Application could later be moved to a different target (since swappability is required, not just a default)
- Support for both a backend service and a frontend (static or served) under one Built Application

Recommend one, with the runner-up and why it lost.

## Answer

**Fly.io**: cheapest at true low-traffic scale (auto-stop/auto-start machines bill near-zero when idle, vs. competitors' flat monthly floors) and the lowest-friction GitHub Actions deploy flow (one secret + one `flyctl deploy` command, no registry hand-off gap, no AWS-style scaffolding).

Runner-up: **Railway** — lost mainly because its Hobby plan's $5 usage credit is shared account-wide (depletes faster as the Factory produces more Built Applications) and its GitHub-Actions deploy path is less standardized than Fly's `flyctl deploy`.

Also ruled out: Render (image-backed-service auto-redeploy gap, pricier always-on floor), a bare VPS (pushes ops burden onto the Factory), AWS ECS Fargate (worse on both cost predictability and setup friction).

Full findings with citations: see branch `research/deploy-target`, file `.scratch/orchestrator-spec/research/deploy-target.md` (commit bbbe2b2).
