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

## Not yet specified

- How Agents obtain secrets/credentials to deploy Built Applications to the chosen target — depends on the deploy-target ([10](issues/10-which-deploy-target.md)) and harness ([07](issues/07-which-agent-harness.md)) picks.
- How Standards updates propagate to, or affect, Built Applications already produced under older Standards.
- Whether/how the Orchestrator handles multiple concurrent Build Runs (queuing, resource contention) — not addressed yet.
- How the spec itself is packaged/published as a deliverable (single doc vs. multiple Standards files) — likely resolves naturally once the Standards-content tickets land; revisit then.

## Out of scope

- Meta-orchestration — the Orchestrator building or extending its own components or new Agent types. Ruled out of this map's destination from the start, not a closed ticket.
