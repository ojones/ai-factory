# Feature-Flag Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology. GrowthBook hosting and per-Built-Application provisioning lives in [ARCHITECTURE.md](ARCHITECTURE.md#feature-flag-infrastructure) — this file covers only what a Built Application's own code must do.

## Flagging policy

Every Agent-authored, user-facing feature/behavior change is wrapped behind its own flag by default — not left to Agent discretion over what counts as "risky." This is the production safety net compensating for the no-PR-review, direct-push-to-main git workflow ([STANDARDS-CODING.md](STANDARDS-CODING.md#git-workflow)).
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)

## Mandatory kill switch

Every Built Application ships, baked into the Starter Template, one global kill-switch flag with a fixed canonical key, checked once in top-level middleware, returning a maintenance response when off — identical across every Built Application, not named/placed ad hoc per project.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)

## Code wiring

A pinned flag-key naming convention, and a single OpenFeature client initialized once at app startup from the SDK connection key env var — not re-derived per feature.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)

## Resilience

Every OpenFeature call site must supply a real, sensible default value. Resilience against a GrowthBook outage comes from OpenFeature's own spec guarantee (flag evaluation always returns the default value on abnormal execution, never throws) — not from any GrowthBook-specific caching behavior.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)
