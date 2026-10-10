# Deployment Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology. Orchestrator-side provisioning (how a new Managed App's repo/secrets get created) lives in [ARCHITECTURE.md](ARCHITECTURE.md#deployment-provisioning) — this file covers only what a Managed App's own repo must contain.

## Containerization

One container per Managed App — the backend serves the built frontend's static assets itself; no separate frontend container or second Fly app. Standard multi-stage Docker build, minimal base image, non-root user, pinned base image digest.
→ [issues/12](.scratch/orchestrator-spec/issues/12-deployment-standards-content.md)

## Registry

GHCR, images tagged by git commit SHA (`ghcr.io/<org>/<app>:<sha>`), plus a floating `latest` tag for convenience that moves only when a commit has passed both the Test Gate and the build. SHA tags are immutable, so the deploy step always references an unambiguous image.
→ [issues/12](.scratch/orchestrator-spec/issues/12-deployment-standards-content.md)

## Workflow split

Two separate GitHub Actions workflow files: `build.yml` (target-agnostic: checkout, build the image with a layer cache, tag by SHA, push to GHCR) and `deploy-fly.yml` (target-specific: `flyctl deploy`, driven by `fly.toml` + a thin provisioning script). `build.yml` runs in parallel with the Test Gate on every push to `main`, not after it; `deploy-fly.yml` starts when either finishes and proceeds only for the run that finds both green for the commit, so nothing deploys unless the Test Gate and the build both pass. The Test Gate installs, type-checks and tests; the image build does the real compile and bundle.

**Swappability** is expressed structurally: the build workflow never changes across targets; moving a Managed App to a different host means replacing only `deploy-fly.yml` (and its referenced native config) with a new deploy workflow — a single, isolated file change by construction.
→ [issues/12](.scratch/orchestrator-spec/issues/12-deployment-standards-content.md)

## Starter Template contents: workflows and Fly config

`build.yml`, `deploy-fly.yml`, and the Test Gate workflow (`test-gate.yml`, triggered on push to `main`) ship as **permanent, unmodified Starter Template content** — every Managed App gets byte-identical copies; App Staging never generates or mutates their YAML.

The one value that varies per Managed App — the Fly app name — is never injected or persisted by App Staging either. Intake already fixes the repo name to the Managed App's name ([ARCHITECTURE.md's Intake section](ARCHITECTURE.md#intake)), so every reference to the Fly app name derives it live from the repo's own name instead of having App Staging template or persist a separate value. Concretely, `fly.toml` has **no `app` field** (a static file can't derive it); `deploy-fly.yml` sets `FLY_APP_NAME` from the repository name and passes `--app` to every `flyctl` call, and `fly/provision.sh` reads `FLY_APP_NAME` from its environment.

**Name collisions**: Fly app names are unique across all of Fly, so the Managed App's name (and therefore its repo name) must be globally free, not merely unused in the Factory's account. App Staging checks this before creating anything and refuses a taken name; pick something distinctive (e.g. prefix with the owner's handle).
→ [issue #21](https://github.com/ojones/ai-factory/issues/21)

## GHCR to Fly image handoff

New container packages on GHCR are private by default, and changing a package's visibility is UI-only (no API), so unattended App Staging can't make them public. Fly can't authenticate to pull a private GHCR image. So `deploy-fly.yml` — the Fly-specific file — pulls the SHA-tagged image from GHCR using the job's own token, re-pushes it to `registry.fly.io/<app>:<sha>`, and deploys from there. GHCR stays the registry of record and `build.yml` is unchanged, so swappability is preserved. If a package does turn out to inherit its public repo's visibility, this step is redundant but harmless.
→ [GitHub docs on package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility), [issue #30](https://github.com/ojones/ai-factory/issues/30)
