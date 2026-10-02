# Feature-Flag Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology. GrowthBook hosting and per-Built-Application provisioning lives in [ARCHITECTURE.md](ARCHITECTURE.md#feature-flag-infrastructure) — this file covers only what a Built Application's own code must do.

## Flagging policy

Every Agent-authored, user-facing feature/behavior change is wrapped behind its own flag by default — not left to Agent discretion over what counts as "risky." This is the production safety net compensating for the no-PR-review, direct-push-to-main git workflow ([STANDARDS-CODING.md](STANDARDS-CODING.md#git-workflow)).
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)

## Mandatory kill switch

Every Built Application ships, baked into the Starter Template, one global kill-switch flag with a fixed canonical key, checked once in top-level middleware, returning a maintenance response when off — identical across every Built Application, not named/placed ad hoc per project.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)

## Code wiring

A pinned flag-key naming convention (`feature.<slug>` for per-feature flags; `global-kill-switch` for the mandatory kill switch), and a single OpenFeature client initialized once at app startup from the SDK connection key env var — not re-derived per feature. The client polls for live flag updates (`pollingInterval`) rather than using SSE streaming, which GrowthBook's own docs confirm is cloud/proxy-only, not available to a bare self-hosted instance.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [build ticket #14](https://github.com/ojones/ai-factory/issues/14)

## Resilience

Every OpenFeature call site must supply a real, sensible default value. Resilience against a GrowthBook outage comes from OpenFeature's own spec guarantee (flag evaluation always returns the default value on abnormal execution, never throws) — not from any GrowthBook-specific caching behavior.

**That default must always be `false` for a boolean flag — never `true`.** Confirmed live against `@openfeature/growthbook-provider@0.1.2`: GrowthBook represents an "off" boolean as `value: null`, and this provider's `translateResult` unconditionally substitutes the caller's default for any `null` value, with no way to distinguish "off" from "not found." Passing `true` makes a flag's off state permanently unobservable — the flag could never actually turn anything off, defeating its entire purpose. The real tradeoff this forces: "intentionally off" and "GrowthBook unreachable" become indistinguishable, so every flag fails *closed* on an outage, not open, for as long as this library bug stands. Revisit this note if a future `@openfeature/growthbook-provider` release fixes it.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [build ticket #14](https://github.com/ojones/ai-factory/issues/14)
