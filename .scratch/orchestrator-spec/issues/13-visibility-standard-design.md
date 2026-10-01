Type: grilling
Status: resolved
Blocked by: 09

## Question

Given the compute platform chosen in [Which ephemeral compute platform for the Orchestrator](09-which-compute-platform.md), what exactly must a Build Run leave behind to satisfy the visibility requirement from [Visibility decision](06-visibility-in-scope.md) — a summary log, a structured report, a failure notification? What's natively available on that platform versus what the Orchestrator must produce itself?

## Answer

**Where it lives**: natively in the GitHub Actions run itself — no separate infrastructure, since the Orchestrator already runs there ([09](09-which-compute-platform.md)).

**Build Run Summary**: written to `GITHUB_STEP_SUMMARY` (native, markdown, renders on the run page — capped at 1MiB/step, 20 summaries/job). Contains: status, what changed, test results, cost spent (surfaced from whatever the cost-guardrail mechanism, [14](14-cost-guardrail-design.md), exposes), and deploy outcome including a direct link to that deployment's Fly log viewer — closing the loop between "what the build did" and "how to check the live app now."

**Raw event log**: OpenHands' headless `--json` mode streams a full JSONL event log live (not an end-of-run dump); this gets uploaded as a build artifact (native `actions/upload-artifact`) rather than crammed into the summary, for the rare deep-dive debugging session. Retention follows GitHub's own default (currently 90 days, configurable 1–400) — per the same "mechanism, not numbers" principle as [05](05-cost-guardrails-mechanism-not-numbers.md), this spec doesn't pin a specific figure.

**Build Run Report**: a curated structured-JSON artifact mirroring the Summary's fields (status, changes, tests, cost, deploy outcome), machine-parseable for any future tooling that aggregates Build Run history. Trivial to produce alongside the Summary since it's the same data.

**Failure notification**: an explicit workflow step auto-creates a GitHub Issue in the Built Application's repo on failure — not a personal GitHub notification-settings toggle (invisible to anyone reading the Standards) and not an external service (no new secrets/infrastructure). Fires on both failure modes a Build Run can end in: a hard crash/error, and "cost/time budget exhausted before CI went green" (per the same-run CI-iteration behavior decided in [11](11-coding-standards-content.md)) — the Issue's title/body distinguishes which, since the two call for different human follow-up (debug a bug vs. extend budget/unblock manually).

**Built Application runtime logging** (deferred here from [11](11-coding-standards-content.md)'s Q12): structured JSON logs to stdout, picked up by Fly.io's native log aggregation — no extra infrastructure.

**Runtime error handling**: a global uncaught-exception/unhandled-rejection handler is required, logging the full error/stack trace (not just the message string) before the process exits — never a silent crash. Costs nothing extra since the stack trace is already on the error object in virtually every language/runtime.
