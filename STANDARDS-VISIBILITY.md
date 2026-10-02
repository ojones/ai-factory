# Visibility Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology. The Orchestrator's own Build Run reporting (summaries, artifacts, failure Issues) lives in [ARCHITECTURE.md](ARCHITECTURE.md#visibility) — this file covers only what a Managed App's own runtime code must do.

## Logging

Managed App code emits structured (JSON) logs to stdout, picked up by Fly.io's native log aggregation — no extra infrastructure.
→ [issues/13](.scratch/orchestrator-spec/issues/13-visibility-standard-design.md)

## Error handling

A global uncaught-exception/unhandled-rejection handler is required, logging the full error/stack trace (not just the message string) before the process exits — never a silent crash.
→ [issues/13](.scratch/orchestrator-spec/issues/13-visibility-standard-design.md)
