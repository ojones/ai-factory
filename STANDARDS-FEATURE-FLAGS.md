# Feature-Flag Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology. GrowthBook hosting and per-Managed-App provisioning lives in [ARCHITECTURE.md](ARCHITECTURE.md#feature-flag-infrastructure) — this file covers only what a Managed App's own code must do.

## Flagging policy

Every Agent-authored, user-facing feature/behavior change is wrapped behind its own flag by default — not left to Agent discretion over what counts as "risky." This is the production safety net compensating for the no-PR-review, direct-push-to-main git workflow ([STANDARDS-CODING.md](STANDARDS-CODING.md#git-workflow)).
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)

## Mandatory kill switch

Every Managed App ships, baked into the Starter Template, one global kill-switch flag, checked once in top-level middleware, returning a maintenance response when off — identical in *shape and placement* across every Managed App, but not a literal identical key (see Code wiring): all Managed Apps share one GrowthBook project, so an app-scoped key is what keeps one app's kill switch from flipping another app's.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [#22](https://github.com/ojones/ai-factory/issues/22)

## Code wiring

All Managed Apps share one GrowthBook project (see [ARCHITECTURE.md](ARCHITECTURE.md#feature-flag-infrastructure) — the free self-hosted tier caps at 1 project), with no GrowthBook-level boundary between apps. The flag-key naming convention carries the only isolation that exists, and so is app-scoped: **`<app-slug>.feature.<slug>`** for per-feature flags, **`<app-slug>.global-kill-switch`** for the mandatory kill switch. The app slug is derived live by the Managed App's own code (e.g. from its repo name, the same env/derivation already used for the Fly app name per [#21](https://github.com/ojones/ai-factory/issues/21)) — never injected or persisted by App Staging, keeping the Starter Template's flag-handling code unmodified per app.

A single OpenFeature client is initialized once at app startup from the SDK connection key env var — not re-derived per feature. The client polls for live flag updates (`pollingInterval`) rather than using SSE streaming, which GrowthBook's own docs confirm is cloud/proxy-only, not available to a bare self-hosted instance.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [build ticket #14](https://github.com/ojones/ai-factory/issues/14), [#22](https://github.com/ojones/ai-factory/issues/22)

## Resilience

Every OpenFeature call site must supply a real, sensible default value. Resilience against a GrowthBook outage comes from OpenFeature's own spec guarantee (flag evaluation always returns the default value on abnormal execution, never throws) — not from any GrowthBook-specific caching behavior.

**That default must always be `false` for a boolean flag — never `true`.** Confirmed live against `@openfeature/growthbook-provider@0.1.2`: GrowthBook represents an "off" boolean as `value: null`, and this provider's `translateResult` unconditionally substitutes the caller's default for any `null` value, with no way to distinguish "off" from "not found." Passing `true` makes a flag's off state permanently unobservable — the flag could never actually turn anything off, defeating its entire purpose. The real tradeoff this forces: "intentionally off" and "GrowthBook unreachable" become indistinguishable, so every flag fails *closed* on an outage, not open, for as long as this library bug stands. Revisit this note if a future `@openfeature/growthbook-provider` release fixes it.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [build ticket #14](https://github.com/ojones/ai-factory/issues/14)
