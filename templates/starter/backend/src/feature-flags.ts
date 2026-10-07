import { OpenFeature, type Client } from "@openfeature/server-sdk";
import { GrowthbookProvider } from "@openfeature/growthbook-provider";
import { timingSafeEqual } from "node:crypto";
import type { RequestHandler, Response } from "express";

/**
 * The app slug scopes every flag key, because all Managed Apps share one
 * GrowthBook project (STANDARDS-FEATURE-FLAGS.md). It is the Fly app name,
 * which is the repo name — Fly sets FLY_APP_NAME at runtime, so nothing is
 * injected per app. APP_SLUG is the override for local runs and tests.
 */
export function appSlug(): string {
  const slug = process.env.FLY_APP_NAME ?? process.env.APP_SLUG;
  if (!slug) {
    throw new Error(
      "FLY_APP_NAME (set by Fly) or APP_SLUG (local runs) is required to scope flag keys."
    );
  }
  return slug;
}

/** Pinned flag-key naming convention: `<app-slug>.global-kill-switch`. */
export const killSwitchKey = (): string => `${appSlug()}.global-kill-switch`;

/** Pinned flag-key naming convention: `<app-slug>.feature.<slug>`. */
export const featureKey = (slug: string): string =>
  `${appSlug()}.feature.${slug}`;

let initialized = false;

/**
 * Initializes the single OpenFeature client once at app startup — call this
 * before app.listen(), not per-request. Call sites read the already-ready
 * client via getFeatureFlagClient().
 */
export async function initFeatureFlags(): Promise<void> {
  if (initialized) return;

  appSlug(); // fail fast at startup, not on the first request

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

const PREVIEW_COOKIE = "preview";

function tokenMatches(supplied: unknown, expected: string): boolean {
  if (typeof supplied !== "string") return false;
  const a = Buffer.from(supplied);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

function readCookie(header: string | undefined, name: string): string | undefined {
  for (const part of (header ?? "").split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) {
      try {
        return decodeURIComponent(rest.join("="));
      } catch {
        return undefined;
      }
    }
  }
  return undefined;
}

/**
 * Preview Token support (STANDARDS-FEATURE-FLAGS.md#preview). A request
 * carrying the token — `X-Preview-Token` header, `?preview=<token>` (which
 * also sets an HttpOnly cookie for browser sessions), or that cookie — sees
 * every `feature.*` flag as on, so a dark feature can be exercised in the
 * real deployment. It never affects the kill switch, which is checked
 * separately in app.ts, and needs no GrowthBook. With PREVIEW_TOKEN unset,
 * preview is disabled entirely.
 */
export function previewMiddleware(): RequestHandler {
  return (req, res, next) => {
    res.locals.preview = false;
    const expected = process.env.PREVIEW_TOKEN;
    if (expected) {
      const query = typeof req.query.preview === "string" ? req.query.preview : undefined;
      const viaQuery = tokenMatches(query, expected);
      if (
        viaQuery ||
        tokenMatches(req.get("x-preview-token"), expected) ||
        tokenMatches(readCookie(req.headers.cookie, PREVIEW_COOKIE), expected)
      ) {
        res.locals.preview = true;
      }
      if (viaQuery) {
        res.cookie(PREVIEW_COOKIE, expected, {
          httpOnly: true,
          sameSite: "strict",
          secure: req.secure,
        });
      }
    }
    next();
  };
}

/**
 * Whether a per-feature flag is on for this request. Use this at every
 * feature call site rather than calling the client directly, so preview
 * works uniformly. The default is `false` (see app.ts for why).
 */
export async function isFeatureEnabled(res: Response, slug: string): Promise<boolean> {
  if (res.locals.preview === true) return true;
  return getFeatureFlagClient().getBooleanValue(featureKey(slug), false);
}
