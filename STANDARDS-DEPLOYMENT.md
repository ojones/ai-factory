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

## Starter Template contents: workflows and Fly config

`build.yml`, `deploy-fly.yml`, and the Test Gate workflow (`test-gate.yml`, triggered on push to `main`) ship as **permanent, unmodified Starter Template content** — every Managed App gets byte-identical copies; App Staging never generates or mutates their YAML.

The one value that varies per Managed App — the Fly app name — is never injected or persisted by App Staging either. Intake already fixes the repo name to the Managed App's name ([ARCHITECTURE.md's Intake section](ARCHITECTURE.md#intake)), so every reference to the Fly app name (`fly.toml`'s `app` field, `fly/provision.sh`'s app-name variable, `deploy-fly.yml`'s Fly-specific steps) derives it live from the repo's own name instead of having App Staging template or persist a separate value.
→ [issue #21](https://github.com/ojones/ai-factory/issues/21)
