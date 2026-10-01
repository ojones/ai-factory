Type: grilling
Status: open

## Question

Per [map.md](../map.md)'s "Not yet specified" list: should the Orchestrator support multiple concurrent Build Runs (queuing, resource contention), or does each Build Run always claim the ephemeral compute exclusively per [Orchestrator host: ephemeral compute](03-orchestrator-host-ephemeral.md)?

If concurrency should be in scope, what's the isolation/queuing mechanism — e.g. one ephemeral runner per Build Run (trivially isolated, no new mechanism needed) vs. parallel sandboxed agents within a single run?

Candidate tooling to evaluate if/when this moves forward: Matt Pocock's [sandcastle](https://github.com/mattpocock/sandcastle) — a TypeScript library that parallelizes sandboxed coding-agent runs via git worktrees + Docker, provider-agnostic as to the underlying agent. Not yet compared against alternatives (e.g. a GitHub Actions matrix build, or just serializing/queuing whole Build Runs). Note it assumes local Docker availability, which GitHub-hosted runners have but which hasn't been verified as sufficient for running several parallel sandboxed containers inside one runner's resource envelope.
