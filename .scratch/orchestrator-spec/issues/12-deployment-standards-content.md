Type: grilling
Status: resolved

## Question

What must the deployment Standards specify — containerization convention, GitHub Actions deploy mechanism, registry choice — given the default target chosen in [Which default deploy target for Built Applications](10-which-deploy-target.md), and how is the swappability requirement from [Deploy target decision](04-deploy-target-default-swappable.md) expressed so a Built Application can move to a different target later?

## Answer

**Containerization**: one container per Built Application — the backend serves the built frontend's static assets itself; no separate frontend container or second Fly app. Standard multi-stage Docker build, minimal base image, non-root user, pinned base image digest.

**Registry**: GHCR, images tagged by git commit SHA (`ghcr.io/<org>/<app>:<sha>`), plus a floating `latest` tag for convenience. SHA tags are immutable, so the deploy step always references an unambiguous image.

**GitHub Actions deploy mechanism**: two separate, chained workflow files — `build.yml` (target-agnostic: checkout, build the image, tag by SHA, push to GHCR) and `deploy-fly.yml` (target-specific: `flyctl deploy`, driven by `fly.toml` + a thin provisioning script for secrets/DNS/certs per [the IaC approach](15-which-iac-approach.md)).

**Secrets/credentials**: the Orchestrator holds a GitHub App installation (not a personal access token) so it can create each new Built Application's repo and push secrets into it unattended and indefinitely, without renewal. Fly.io access is a single shared org-level API token, pushed as the `FLY_API_TOKEN` secret into every new Built Application repo.

**Swappability**: expressed structurally, not just by image portability — the build workflow never changes across targets; moving a Built Application to a different host means replacing only `deploy-fly.yml` (and its referenced native config, e.g. `fly.toml` → a Railway/Render equivalent) with a new deploy workflow. This makes "swap the target" a single, isolated file change by construction.

**Out of scope for this ticket**: feature-flag conventions (GrowthBook/OpenFeature, [issue 16](16-which-feature-flag-tool.md)) — split into [Feature-flag Standards content](18-feature-flag-standards-content.md), since flags are a release/testing concern layered on top of deployment, not part of the deploy mechanism itself.
