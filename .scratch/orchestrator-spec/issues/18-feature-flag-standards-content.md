Type: grilling
Status: resolved
Blocked by: 16

## Question

Given the feature-flag tool choice in [Which feature-flag tool for Built Applications](16-which-feature-flag-tool.md) (GrowthBook, with app code written against OpenFeature), what must the Standards specify for a Built Application to actually use feature flags in practice — e.g. how a new Built Application provisions its own GrowthBook project/API key, whether any flags are mandatory by convention (such as a global kill switch), how flag state is wired through OpenFeature in the app's code, and how this interacts with the deployment mechanism from [Deployment Standards content](12-deployment-standards-content.md)?

## Answer

**Hosting**: one shared, always-on GrowthBook instance — not one per Built Application, which would double the deployed-infrastructure footprint of every app this Factory produces just to get flags. Backed by a managed MongoDB Atlas free-tier cluster (GrowthBook requires MongoDB, not Postgres — corrects an assumption in the original tool-choice research), consistent with this spec's standing preference for managed stateful services over self-hosting one's own database (same principle as [02](02-model-serving-api-not-selfhosted.md)).

**Provisioning**: GrowthBook's REST API can create a project (`POST /v1/projects`) and a per-project, read-only SDK connection key (`POST /v1/sdk-connections`) programmatically — but admin-scoped API keys can only be created via GrowthBook's UI, not its API. So the Orchestrator holds one manually-created, admin-scoped GrowthBook Personal Access Token (a one-time setup exception to full automation), and at the start of each Build Run uses it to create that Built Application's project — single "production" environment only, no dev/staging split, matching the fact that nothing else in this spec's deploy model (ticket 12) has a staging environment — plus a scoped SDK connection key, which gets pushed into the new repo's secrets the same way ticket 12 pushes the Fly API token.

**Flagging policy**: every Agent-authored, user-facing feature/behavior change is wrapped behind its own flag by default, not left to Agent discretion over what counts as "risky." This is the production safety net the owner wanted (per [16](16-which-feature-flag-tool.md)'s original research question), directly compensating for [11](11-coding-standards-content.md)'s no-PR-review, direct-push-to-main workflow.

**Mandatory kill switch**: every Built Application ships, baked into the Starter Template ([11](11-coding-standards-content.md)/[20](20-which-application-stack.md)), one global kill-switch flag with a fixed canonical key, checked once in top-level middleware, returning a maintenance response when off — identical across every Built Application rather than named/placed ad hoc per project.

**Code wiring**: a pinned flag-key naming convention, and a single OpenFeature client initialized once at app startup from the SDK connection key env var — not re-derived per feature by each Agent.

**Resilience**: every OpenFeature call site must supply a real, sensible default value. Resilience against a GrowthBook outage comes from OpenFeature's own spec guarantee (Requirement 1.4.10: flag evaluation always returns the default value on abnormal execution, never throws) — not from any GrowthBook-specific caching behavior, which isn't confirmed to exist in its OpenFeature provider wrapper.
