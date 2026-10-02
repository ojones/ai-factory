import { createApp } from "./app";
import { logger } from "./logger";
import { initFeatureFlags } from "./feature-flags";

/**
 * Required global error handler (STANDARDS-VISIBILITY.md): log the full
 * error — including stack trace, not just the message — before exiting.
 * A silent crash (or one that only logs `error.message`) loses the
 * information needed to debug it after the process is gone.
 */
process.on("uncaughtException", (error: Error) => {
  logger.error("uncaught_exception", {
    name: error.name,
    message: error.message,
    stack: error.stack,
  });
  process.exit(1);
});

process.on("unhandledRejection", (reason: unknown) => {
  const error = reason instanceof Error ? reason : new Error(String(reason));
  logger.error("unhandled_rejection", {
    name: error.name,
    message: error.message,
    stack: error.stack,
  });
  process.exit(1);
});

const PORT = Number(process.env.PORT ?? 3000);

async function main() {
  // The single OpenFeature client is initialized once here, before the
  // server starts accepting requests — not re-derived per route/request.
  await initFeatureFlags();

  const app = createApp();

  app.listen(PORT, () => {
    logger.info("server_started", { port: PORT });
  });
}

main();
