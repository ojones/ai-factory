/**
 * Minimal structured (JSON) logger — one line of JSON per log call, written
 * to stdout. Per STANDARDS-VISIBILITY.md, Managed App logs must be
 * structured JSON on stdout (Fly.io's log aggregation reads it directly, no
 * extra logging infra needed), so this intentionally does not shell out to a
 * logging framework — a few lines of JSON.stringify is the whole job.
 */

type LogLevel = "debug" | "info" | "warn" | "error";

type LogFields = Record<string, unknown>;

function write(level: LogLevel, message: string, fields: LogFields = {}): void {
  const entry = {
    timestamp: new Date().toISOString(),
    level,
    message,
    ...fields,
  };
  console.log(JSON.stringify(entry));
}

export const logger = {
  debug: (message: string, fields?: LogFields) => write("debug", message, fields),
  info: (message: string, fields?: LogFields) => write("info", message, fields),
  warn: (message: string, fields?: LogFields) => write("warn", message, fields),
  error: (message: string, fields?: LogFields) => write("error", message, fields),
};
