import path from "node:path";
import express, { type Express } from "express";
import { logger } from "./logger";
import { healthRouter } from "./routes/health";
import { GLOBAL_KILL_SWITCH_KEY, getFeatureFlagClient } from "./feature-flags";

// The built frontend lives at ../../frontend/dist relative to this file's
// compiled location (dist/app.js -> backend/dist -> backend/.. -> frontend/dist).
// The Dockerfile's final stage preserves this same backend/ + frontend/
// sibling layout under /app, so the relative path holds in the container too.
const DEFAULT_FRONTEND_DIST = path.resolve(__dirname, "../../frontend/dist");
const FRONTEND_DIST = process.env.FRONTEND_DIST_PATH
  ? path.resolve(process.env.FRONTEND_DIST_PATH)
  : DEFAULT_FRONTEND_DIST;

export function createApp(): Express {
  const app = express();

  app.use(express.json());

  // One structured JSON log line per request (STANDARDS-VISIBILITY.md).
  app.use((req, res, next) => {
    res.on("finish", () => {
      logger.info("request", {
        method: req.method,
        path: req.path,
        status: res.statusCode,
      });
    });
    next();
  });

  // Mounted before the kill switch so health checks (Fly's included) keep
  // working even in maintenance mode — infrastructure shouldn't be gated by
  // an application-level flag.
  app.use(healthRouter);

  // Mandatory global kill switch (STANDARDS-FEATURE-FLAGS.md): checked once
  // here, not re-derived per route. Everything mounted after this — the
  // static frontend, and any Built-Application-specific API routes — is
  // gated by it.
  //
  // The default passed here MUST be `false`, not `true` — confirmed live
  // against @openfeature/growthbook-provider@0.1.2: GrowthBook represents
  // an "off" boolean as `value: null`, and this provider's translateResult
  // unconditionally substitutes the caller's default for any null value,
  // with no way to tell "off" apart from "not found"/an outage. Passing
  // `true` would make the flag's off state permanently unobservable — the
  // flag could never actually turn anything off. The real tradeoff this
  // creates: both "intentionally off" and "GrowthBook unreachable" collapse
  // to the same default, so this also means the kill switch fails *closed*
  // (maintenance mode) on an outage, not open — the opposite of
  // STANDARDS-FEATURE-FLAGS.md's general resilience principle, but the
  // conservative choice for a kill switch specifically, and the only one
  // this library's bug actually permits.
  app.use(async (req, res, next) => {
    const client = getFeatureFlagClient();
    const enabled = await client.getBooleanValue(GLOBAL_KILL_SWITCH_KEY, false);
    if (!enabled) {
      res.status(503).json({
        status: "maintenance",
        message: "This application is temporarily unavailable.",
      });
      return;
    }
    next();
  });

  // One container: the backend serves the built frontend's static assets
  // itself (STANDARDS-DEPLOYMENT.md) — no separate frontend server.
  app.use(express.static(FRONTEND_DIST));

  // SPA fallback: any unmatched GET that isn't an API route falls through
  // to index.html so client-side routing survives a hard refresh/deep link.
  app.use((req, res, next) => {
    if (req.method !== "GET" || req.path.startsWith("/api/")) {
      next();
      return;
    }
    res.sendFile(path.join(FRONTEND_DIST, "index.html"), (err) => {
      if (err) {
        next(err);
      }
    });
  });

  return app;
}
