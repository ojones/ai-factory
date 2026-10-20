import { OpenFeature, TypedInMemoryProvider } from "@openfeature/server-sdk";
import { featureKey } from "../feature-flags";

function provider(slug: string, on: boolean) {
  return new TypedInMemoryProvider({
    [featureKey(slug)]: { variants: { on: true, off: false }, defaultVariant: on ? "on" : "off" },
  });
}

// Runs `fn` with the feature flag `slug` forced on or off, then puts the previous provider back. Every flag in flags.json needs a
// withFlag(slug, false, ...) test (the old behaviour is unchanged) and a withFlag(slug, true, ...) test (the new behaviour); `npm run check` enforces it.
export async function withFlag<T>(slug: string, on: boolean, fn: () => T | Promise<T>): Promise<T> {
  const previous = OpenFeature.getProvider();
  await OpenFeature.setProviderAndWait(provider(slug, on));
  try {
    return await fn();
  } finally {
    await OpenFeature.setProviderAndWait(previous);
  }
}
