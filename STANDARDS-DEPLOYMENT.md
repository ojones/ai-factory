# Deployment Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology. Orchestrator-side provisioning (how a new Managed App's repo/secrets get created) lives in [ARCHITECTURE.md](ARCHITECTURE.md#deployment-provisioning) — this file covers only what a Managed App's own repo must contain.

## Containerization

One container per Managed App — the backend serves the built frontend's static assets itself; no separate frontend container or second Fly app. Standard multi-stage Docker build, minimal base image, non-root user, pinned base image digest.
→ [issues/12](.scratch/orchestrator-spec/issues/12-deployment-standards-content.md)

## Registry

GHCR, images tagged by git commit SHA (`ghcr.io/<org>/<app>:<sha>`), plus a floating `latest` tag for convenience. SHA tags are immutable, so the deploy step always references an unambiguous image.
→ [issues/12](.scratch/orchestrator-spec/issues/12-deployment-standards-content.md)

## Workflow split

Two separate, chained GitHub Actions workflow files: `build.yml` (target-agnostic: checkout, build the image, tag by SHA, push to GHCR) and `deploy-fly.yml` (target-specific: `flyctl deploy`, driven by `fly.toml` + a thin provisioning script).

**Swappability** is expressed structurally: the build workflow never changes across targets; moving a Managed App to a different host means replacing only `deploy-fly.yml` (and its referenced native config) with a new deploy workflow — a single, isolated file change by construction.
→ [issues/12](.scratch/orchestrator-spec/issues/12-deployment-standards-content.md)
