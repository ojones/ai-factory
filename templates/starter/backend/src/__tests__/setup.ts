import { OpenFeature, TypedInMemoryProvider } from "@openfeature/server-sdk";

// Flag keys are scoped by app slug (feature-flags.ts); tests use a fixed one.
process.env.APP_SLUG = "test-app";

// Tests never call initFeatureFlags() (that would hit the real shared
// GrowthBook instance). This in-memory provider starts empty, so every
// feature flag reads off; a test that needs a flag on or off uses
// `withFlag(slug, on, fn)` from ./with-flag.
OpenFeature.setProvider(new TypedInMemoryProvider({}));
