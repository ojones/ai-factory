# Shared GrowthBook instance

The Factory's one shared, always-on GrowthBook instance, per
[ARCHITECTURE.md](../../ARCHITECTURE.md#feature-flag-infrastructure) and
[issue #13](https://github.com/ojones/ai-factory/issues/13). Not a Built
Application — this is Factory-level shared infrastructure every Built
Application's GrowthBook project lives inside.

- **App**: `ai-factory-growthbook` on Fly.io, deployed directly from the
  official `growthbook/growthbook:latest` image (no Dockerfile/build step —
  GrowthBook ships as a single pre-built image bundling its Next.js
  front-end, Express API, and Python stats engine).
- **Database**: a MongoDB Atlas free-tier (M0) cluster, provisioned manually
  (Atlas has no self-serve API key issued by default; this was a one-time
  manual setup).
- **Ports**: 3000 (app/front-end) and 3100 (API/back-end) both need to be
  publicly reachable — GrowthBook's own docs are explicit that these must be
  on unique ports if served from the same domain.
- **Memory**: needs at least 2GB. The default 512MB (what seemed like a
  reasonable starting guess) silently OOM-killed both the back-end and
  front-end processes repeatedly — bundling three runtimes in one container
  is genuinely memory-hungry. If GrowthBook is ever OOM-killed again, that's
  the first thing to check (`fly logs`, look for "Out of memory: Killed
  process").

## Deploying / redeploying

```bash
cd infra/growthbook
fly deploy --remote-only
```

Secrets (`MONGODB_URI`, `JWT_SECRET`, `ENCRYPTION_KEY`, `NODE_ENV`,
`APP_ORIGIN`, `API_HOST`) are set directly on the Fly app via `fly secrets
set` — not stored in this repo. See
[GrowthBook's env var docs](https://docs.growthbook.io/self-host/env) for
what each one does.

## One-time manual steps (already done; recorded for reference)

1. Create the Fly app, a persistent volume for uploads, and set the secrets
   above.
2. Deploy.
3. Visit the app's URL once to create the first admin account (GrowthBook's
   own first-run signup flow).
4. Create an admin-scoped Personal Access Token via the GrowthBook UI
   (Settings → API Keys / Personal Access Tokens) — GrowthBook has no API to
   create this token for you, so this one step stays manual per
   ARCHITECTURE.md. The Orchestrator holds this token to provision each new
   Managed App's own GrowthBook project.
