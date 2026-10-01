Type: research
Status: claimed

## Question

Given deployment Standards should pin one default hosting target while keeping it swappable per project (see [Deploy target decision](04-deploy-target-default-swappable.md)), which target should be the default for Built Applications (backend+frontend, containerized, deployed via GitHub)?

Compare candidates (e.g. Fly.io, Railway, Render, a bare VPS running Docker Compose, AWS ECS Fargate, and any other cheap container-hosting option) against:
- Cost at small scale (a handful of low-traffic apps)
- Friction of a Docker image + GitHub Actions deploy flow
- How easily a given Built Application could later be moved to a different target (since swappability is required, not just a default)
- Support for both a backend service and a frontend (static or served) under one Built Application

Recommend one, with the runner-up and why it lost.
