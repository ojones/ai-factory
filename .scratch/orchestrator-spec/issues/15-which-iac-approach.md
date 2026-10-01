Type: research
Status: resolved

## Question

Given the default deploy target [Fly.io](10-which-deploy-target.md) and the swappability requirement from [Deploy target decision](04-deploy-target-default-swappable.md), what infrastructure-as-code approach should the deployment Standards mandate for provisioning Built Application infrastructure (Fly app/machine config, DNS, secrets, registry)? Compare `fly.toml` alone, Terraform (with the community Fly provider), Pulumi, and any other credible option, for: how well it stays declarative/versioned in git, cost/maintenance overhead, and how cleanly it supports swapping to a different deploy target later.

Recommend one, with the runner-up and why it lost.

## Answer

**`fly.toml` (checked into each Built Application's repo) as the sole declarative app-config, paired with a thin, checked-in, idempotent provisioning script/CI step** for the few things it can't express (secrets, DNS/certs, registry auth). This is Fly.io's own current recommendation, costs nothing extra, and is fully Agent-readable/writable git state.

Runner-up: **Terraform** (community `ampbase-io/terraform-provider-fly` provider) — loses because Fly.io's own official provider was archived in March 2024 and Fly's docs now explicitly recommend against Terraform for structural reasons (its plan/apply model doesn't fit the Machines API's imperative lifecycle); it also adds a state-backend dependency without delivering real cross-provider portability, since Railway/Render Terraform support is equally thin.

Also ruled out: Pulumi (no official Fly provider ever shipped; community packages are thinner than Terraform's).

Full findings with citations: see branch `research/iac-approach`, file `.scratch/orchestrator-spec/research/iac-approach.md` (commit 02bd5e5).
