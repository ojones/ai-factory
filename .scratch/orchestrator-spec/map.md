# Orchestrator architecture + standards spec

## Destination

A handoff-ready architecture + standards spec defining: the Orchestrator's model/hosting stack (a specific open-weight model + specific cheap cloud provider, pinned), Agent-friendly coding Standards, and containerized GitHub-based deployment Standards — sufficient to hand off to a later build effort for a v1 Orchestrator that produces separate, external Built Applications (backend+frontend). Meta-orchestration (the Orchestrator extending/building more of itself) is explicitly out of scope.

## Notes

- Cost-consciousness and an open-source/open-weight lean govern every tradeoff in this map.
- This map produces a **spec** (decisions + Standards content), not running code. Building the v1 Orchestrator is a separate, later map.
- Glossary terms (Factory, Orchestrator, Agent, Standards, Built Application, Build Run) are fixed in [GLOSSARY.md](../../GLOSSARY.md) at the repo root — use them, don't reinvent.
- Research tickets: call the Skill tool with "research".
- Standards-content / design tickets: call the Skill tool twice, for "grilling" and "domain-modeling".

## Decisions so far

- [Agent runtime: reuse existing open-source harness](issues/01-agent-runtime-reuse-harness.md): reuse an existing open-source CLI coding-agent harness rather than a custom LLM loop.
- [Model serving: pay-per-token API, not self-hosted](issues/02-model-serving-api-not-selfhosted.md): consume open-weight models via a pay-per-token API provider rather than self-hosted GPU inference.
- [Orchestrator host shape: ephemeral compute](issues/03-orchestrator-host-ephemeral.md): the Orchestrator runs as ephemeral compute during a Build Run, not an always-on service.
- [Deploy target: default + swappable](issues/04-deploy-target-default-swappable.md): deployment Standards pin one default hosting target for Built Applications, but the mechanism must stay swappable per project.
- [Cost guardrails: mechanism, not numbers](issues/05-cost-guardrails-mechanism-not-numbers.md): the spec requires a budget cap + hard stop exist and are enforced; concrete dollar figures are a build-time config, not part of this spec.
- [Visibility: in-scope requirement](issues/06-visibility-in-scope.md): a minimum observability/reporting requirement for unattended Build Runs is part of the architecture, though its implementation is deferred.
- [Which ephemeral compute platform for the Orchestrator](issues/09-which-compute-platform.md): GitHub Actions — native scheduling, secrets, and logging with no extra infrastructure; runner-up Fly Machines.
- [Which open-source agent harness](issues/07-which-agent-harness.md): OpenHands — MIT, SWE-bench-leading, pluggable to open-weight models, headless CLI with JSON output; runner-up mini-swe-agent.
- [Which default deploy target for Built Applications](issues/10-which-deploy-target.md): Fly.io — cheapest at low-traffic scale, lowest-friction GitHub Actions deploy flow; runner-up Railway.
- [Which API provider + open-weight model](issues/08-which-model-provider.md): DeepInfra serving Qwen3-Coder-480B-A35B-Instruct-Turbo — cheapest agent-RL-trained open-weight coder; runner-up Together AI (same model).
- [Which IaC approach for Built Application deploys](issues/15-which-iac-approach.md): `fly.toml` + a thin provisioning script, not Terraform/Pulumi — Fly's own official Terraform provider is archived and un-recommended by Fly.io itself.
- [Which feature-flag tool for Built Applications](issues/16-which-feature-flag-tool.md): GrowthBook, with app code written against OpenFeature; runner-up Unleash.
- [Deployment Standards content](issues/12-deployment-standards-content.md): one container per Built App (backend serves frontend), GHCR images tagged by git SHA, build/deploy split into two chained GitHub Actions workflow files for swappability, a GitHub App + one shared Fly org token for unattended secret provisioning.
- [Coding Standards content](issues/11-coding-standards-content.md): one pinned stack seeded from a fixed Starter Template, `AGENTS.md` for rule discovery, hard CI test gate (unit + smoke, no coverage threshold), mechanical-only style, direct push to main with same-run CI-failure iteration, env-var-only secrets, OSS-default dependencies.
- [Visibility standard design](issues/13-visibility-standard-design.md): Build Run Summary in the GitHub Actions job summary (status/changes/tests/cost/deploy link), raw OpenHands JSONL as an artifact, a machine-readable Build Run Report, a GitHub Issue on failure (crash vs. budget-exhausted), and Built Application runtime JSON logging + a required global error handler.
- [Cost guardrail design](issues/14-cost-guardrail-design.md): cap scoped to LLM token spend only, tracked by summing DeepInfra's per-response `usage.estimated_cost`, breach refuses the next turn after the current one finishes, backed by a per-Build-Run scoped API credential with an embedded max-USD limit as a provider-side second line of defense.

## Open tickets

Blocked-by research now resolved, so these Standards-content/design tickets are unblocked and ready to work:

- [Feature-flag Standards content](issues/18-feature-flag-standards-content.md) — blocked by 16 (feature-flag tool), now resolved.
- [Which application stack](issues/20-which-application-stack.md) — spun off from ticket 11; blocked by 11, now resolved.

## Not yet specified

- How Standards updates propagate to, or affect, Built Applications already produced under older Standards.
- Whether/how the Orchestrator handles multiple concurrent Build Runs (queuing, resource contention) — a future concern, not in scope for this spec pass; tracked in [Concurrent Build Runs](issues/19-concurrent-build-runs.md).
- How the spec itself is packaged/published as a deliverable (single doc vs. multiple Standards files) — likely resolves naturally once the Standards-content tickets land; revisit then.

## Out of scope

- Meta-orchestration — the Orchestrator building or extending its own components or new Agent types. Ruled out of this map's destination from the start, not a closed ticket.

## Related tooling, outside this map's destination

- [Which wiki tool for Factory context](issues/17-which-wiki-tool.md): Wiki.js in git-sync mode; runner-up MkDocs Material on GitHub Pages. Researched alongside the above at the owner's request, but this is tooling for how the Factory's own docs are authored/viewed, not part of the Orchestrator spec deliverable — doesn't feed the handoff.
