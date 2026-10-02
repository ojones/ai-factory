# Orchestrator Architecture

Decisions about how the Orchestrator itself is built and operated — for whoever implements the v1 Orchestrator. Distinct from [STANDARDS.md](STANDARDS.md): nothing here is something a Managed App's own code needs to follow. Terminology follows [GLOSSARY.md](GLOSSARY.md).

Each decision links back to its ticket in `.scratch/orchestrator-spec/issues/` for the full comparison, runner-ups, and citations.

## Agent runtime

The Orchestrator reuses an existing open-source CLI coding-agent harness rather than a custom LLM loop — shrinks build scope and matches the Factory's open-source lean.

**Harness: [OpenHands](https://github.com/All-Hands-AI/OpenHands)** (MIT). SWE-bench-leading, pluggable to open-weight models via LiteLLM, purpose-built `--headless` CLI mode with `--json` structured output. Runner-up: mini-swe-agent.
→ [issues/01](.scratch/orchestrator-spec/issues/01-agent-runtime-reuse-harness.md), [issues/07](.scratch/orchestrator-spec/issues/07-which-agent-harness.md)

## Model serving

Open-weight model inference is consumed via a pay-per-token API, not self-hosted GPU inference — Build Runs are bounded, not continuously GPU-saturated, so idle self-hosted cost would dominate.

**Provider/model: [DeepInfra](https://deepinfra.com) serving `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo`** (Apache 2.0). Cheapest confirmed per-token price for a model RL-trained for long multi-turn tool-calling agentic loops; leads open-weight models on agentic tool-use benchmarks. Runner-up: Together AI (same model).
→ [issues/02](.scratch/orchestrator-spec/issues/02-model-serving-api-not-selfhosted.md), [issues/08](.scratch/orchestrator-spec/issues/08-which-model-provider.md)

## Orchestrator host

The Orchestrator runs as ephemeral compute during a Build Run, not an always-on service — pay only while a Build Run is active.

**Platform: GitHub Actions** (GitHub-hosted runners). Native scheduling (`on.schedule`), secrets, and run logging with zero extra infrastructure; clears the 6-hour-per-job duration bar for an overnight run. Runner-up: Fly Machines.
→ [issues/03](.scratch/orchestrator-spec/issues/03-orchestrator-host-ephemeral.md), [issues/09](.scratch/orchestrator-spec/issues/09-which-compute-platform.md)

## Deploy target for Managed Apps

Deployment pins one default hosting target for v1 simplicity, but the mechanism must stay swappable per project — never hardcode an assumption the target is fixed forever.

**Default: [Fly.io](https://fly.io)**. Cheapest at low-traffic scale, lowest-friction GitHub Actions deploy flow. Runner-up: Railway.
→ [issues/04](.scratch/orchestrator-spec/issues/04-deploy-target-default-swappable.md), [issues/10](.scratch/orchestrator-spec/issues/10-which-deploy-target.md)

**IaC approach: `fly.toml`** (checked into each Managed App's repo) as the sole declarative app-config, paired with a thin, checked-in, idempotent provisioning script for what it can't express (secrets, DNS/certs, registry auth). Fly's own current recommendation — their official Terraform provider is archived and un-recommended by Fly.io itself.
→ [issues/15](.scratch/orchestrator-spec/issues/15-which-iac-approach.md)

## Cost guardrails

The spec requires a budget cap + hard stop exist and are enforced; concrete dollar figures are build-time config, not part of this spec.

**Enforcement mechanism**: the cap covers LLM token spend only (not GitHub Actions minutes or other metered calls). The Orchestrator sums the `usage.estimated_cost` field DeepInfra returns on every chat-completion response and compares the running total to the per-run cap after every LLM call. On breach, the current turn finishes cleanly and the next turn is simply refused — never a mid-call abort. As a provider-side second line of defense, each Build Run is issued its own scoped API credential (a JWT with an embedded max-USD limit equal to that run's own cap).
→ [issues/05](.scratch/orchestrator-spec/issues/05-cost-guardrails-mechanism-not-numbers.md), [issues/14](.scratch/orchestrator-spec/issues/14-cost-guardrail-design.md)

## Visibility

A minimum observability/reporting requirement for unattended Build Runs is part of the architecture.

**Mechanism**: a **Build Run Summary** written to `GITHUB_STEP_SUMMARY` (status, what changed, test results, cost spent, deploy outcome + a link to that deployment's Fly log viewer). The raw OpenHands `--json` JSONL event stream is uploaded as a build artifact for deep-dive debugging. A curated, machine-readable **Build Run Report** (same fields as the Summary) is produced alongside it for future tooling. On failure — a crash, or the cost/time budget exhausted before CI went green — an explicit workflow step auto-creates a GitHub Issue in the Managed App's repo, distinguishing which.
→ [issues/06](.scratch/orchestrator-spec/issues/06-visibility-in-scope.md), [issues/13](.scratch/orchestrator-spec/issues/13-visibility-standard-design.md)

## Deployment provisioning

For each new Managed App, the Orchestrator creates its repo and pushes deploy secrets into it unattended: one GitHub App installation (not a personal access token, so it works indefinitely without renewal) for repo creation/secrets, and a single shared Fly.io org-level API token pushed as the `FLY_API_TOKEN` secret into every new repo.
→ [issues/12](.scratch/orchestrator-spec/issues/12-deployment-standards-content.md)

## Feature-flag infrastructure

**Tool: [GrowthBook](https://www.growthbook.io)** (MIT core), with Managed App code written against **OpenFeature** rather than GrowthBook's SDK directly. Runner-up: Unleash.
→ [issues/16](.scratch/orchestrator-spec/issues/16-which-feature-flag-tool.md)

**Hosting**: one shared, always-on GrowthBook instance — not one per Managed App — backed by a managed MongoDB Atlas free-tier cluster (GrowthBook requires MongoDB, not Postgres). The Orchestrator holds one manually-created, admin-scoped GrowthBook Personal Access Token (a one-time setup exception to full automation, since GrowthBook's API can't create admin keys itself). At the start of each Build Run it calls GrowthBook's REST API to create that Managed App's project (single "production" environment) and a scoped, read-only SDK connection key, which gets pushed into the new repo's secrets alongside the Fly token.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)
