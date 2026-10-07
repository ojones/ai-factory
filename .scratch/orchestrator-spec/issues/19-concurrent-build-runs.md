Type: grilling
Status: resolved

## Question

Per [map.md](../map.md)'s "Not yet specified" list: should the Orchestrator support multiple concurrent Build Runs (queuing, resource contention), or does each Build Run always claim the ephemeral compute exclusively per [Orchestrator host: ephemeral compute](03-orchestrator-host-ephemeral.md)?

If concurrency should be in scope, what's the isolation/queuing mechanism — e.g. one ephemeral runner per Build Run (trivially isolated, no new mechanism needed) vs. parallel sandboxed agents within a single run?

Candidate tooling to evaluate if/when this moves forward: Matt Pocock's [sandcastle](https://github.com/mattpocock/sandcastle) — a TypeScript library that parallelizes sandboxed coding-agent runs via git worktrees + Docker, provider-agnostic as to the underlying agent. Not yet compared against alternatives (e.g. a GitHub Actions matrix build, or just serializing/queuing whole Build Runs). Note it assumes local Docker availability, which GitHub-hosted runners have but which hasn't been verified as sufficient for running several parallel sandboxed containers inside one runner's resource envelope.


## Answer

**Two cases, handled separately.**
- **Different Managed Apps concurrently:** allowed. Each app's Build Run runs on its own GitHub Actions runner (the Build Run workflow lives in ai-factory and checks out the Managed App repo — see [#23](https://github.com/ojones/ai-factory/issues/23)), so no new isolation mechanism is needed. Two shared resources need care: cost tracking must be per-Build-Run (the per-run scoped credential's own usage, not DeepInfra's account-wide total, or simultaneous runs would trip each other's cap), and the number of simultaneous Build Runs is a single configurable cap, not a queue.
- **Same Managed App concurrently:** serialized. Tool: GitHub Actions' native `concurrency:` group, one group per Managed App, `cancel-in-progress: false`. This guarantees non-overlap only. A group holds one running and one pending job, and a newer pending job replaces an older one.

**Requirement for the displacement gap:** no accepted request may be dropped. The trigger layer (Intake / App Staging) must record every request durably, and a finished Build Run checks for unprocessed requests and re-dispatches. Where that record lives is decided by the Intake successor map.

**Tooling comparison, resolved:** sandcastle rejected (solves parallel runs on one repo; serializing makes that unnecessary, and it only helps if Build Runs stop pushing directly to main). Actions matrix rejected (fans out within one run, not the problem). Merge queue rejected for v1 (PR-only; Standards push directly to main). Community FIFO queue actions and an external queue service rejected (third-party dependency / extra infrastructure for a v1 stepping stone).

**Unverified:** the concurrency-group semantics above are from memory, not checked against current GitHub docs. Confirm at build time.
