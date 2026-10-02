import { OpenFeature, type Client } from "@openfeature/server-sdk";
import { GrowthbookProvider } from "@openfeature/growthbook-provider";

/**
 * Pinned flag-key naming convention (STANDARDS-FEATURE-FLAGS.md): per-feature
 * flags use `feature.<slug>`; the mandatory kill switch uses this fixed key,
 * identical across every Managed App.
 */
export const GLOBAL_KILL_SWITCH_KEY = "global-kill-switch";

let initialized = false;

/**
 * Initializes the single OpenFeature client once at app startup — call this
 * before app.listen(), not per-request. Call sites read the already-ready
 * client via getFeatureFlagClient().
 */
export async function initFeatureFlags(): Promise<void> {
  if (initialized) return;

  const clientKey = process.env.GROWTHBOOK_CLIENT_KEY;
  if (!clientKey) {
    throw new Error(
      "GROWTHBOOK_CLIENT_KEY is required to initialize feature flags."
    );
  }
  const apiHost =
    process.env.GROWTHBOOK_API_HOST ??
    "https://ai-factory-growthbook.fly.dev:3100";

  // pollingInterval keeps this long-running process's flags fresh without
  // a redeploy. `streaming: true` (SSE) was tried first, per the provider's
  // own README — but found live, by testing against the real instance, to
  // require Node's `eventsource` package + setPolyfills(), which GrowthBook
  // only warns about at runtime rather than failing fast. Polling has no
  // such dependency and is simpler for what this needs.
  await OpenFeature.setProviderAndWait(
    new GrowthbookProvider({ apiHost, clientKey }, { pollingInterval: 5000 })
  );
  initialized = true;
}

export function getFeatureFlagClient(): Client {
  return OpenFeature.getClient();
}
