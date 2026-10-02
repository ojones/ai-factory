import { OpenFeature, TypedInMemoryProvider } from "@openfeature/server-sdk";

// Tests never call initFeatureFlags() (that would hit the real shared
// GrowthBook instance) — without a provider, OpenFeature's default no-op
// provider returns whatever default each call site passes, which is
// `false` (see app.ts for why it must be `false`, not `true`). That would
// make every gated route 503 in tests. This in-memory provider defaults
// the kill switch "on" so existing functional tests exercise normal
// behavior; a test that specifically needs the "off" case can call
// `OpenFeature.getProvider().putConfiguration(...)` to flip it. Extend
// this with new flags as this Built Application adds them.
OpenFeature.setProvider(
  new TypedInMemoryProvider({
    "global-kill-switch": {
      variants: { on: true, off: false },
      defaultVariant: "on",
    },
  })
);
