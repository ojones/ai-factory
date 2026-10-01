Type: grilling
Status: resolved
Blocked by: 07

## Question

What must the coding Standards actually specify for them to be agent-friendly — repo conventions, test requirements, how Agents discover the rules (e.g. an AGENTS.md-style file), and anything specific to the harness chosen in [Which open-source agent harness](07-which-agent-harness.md)?

## Answer

**Stack**: one pinned language/framework stack (backend + frontend) for every Built Application — not re-derived per project. The specific stack is split out to [Which application stack](20-which-application-stack.md), since it's a concrete comparison decision like the harness/model/deploy-target picks, not a policy question.

**Starter Template**: the Orchestrator seeds every new Built Application from a fixed Starter Template (directory structure, CI config, boilerplate) rather than having the Agent build repo structure from scratch each Build Run. Cheaper in agent tokens and keeps every Built Application structurally identical.

**Rule discovery**: `AGENTS.md` at the repo root — OpenHands natively auto-loads this into its system prompt (also recognizes `CLAUDE.md`/`GEMINI.md`/`.cursorrules` as equivalents; docs.openhands.dev/overview/skills). The Starter Template seeds its base content (stack, structure, how to run tests/build, pointers to the Standards); Agents are expected to extend it with project-specific notes as the Built Application grows, the same way the convention is used elsewhere — a file nobody updates goes stale.

**Test gate**: hard gate in the ticket-12 GitHub Actions pipeline, not Agent judgment. Required: unit tests for business logic, plus one minimal boot/health-check smoke test. No coverage-percentage threshold — not a meaningful signal for agent-written, single-Build-Run code, and easy to game.

**Style**: purely mechanical — an auto-formatter is the entire style guide, no prose conventions (naming philosophy, comment density, etc.) for an Agent to probabilistically get wrong. Built Applications aren't normally read day-to-day by a human.

**Git workflow**: Agents push directly to the Built Application's main branch — no PR/review gate. The same Agent would be both author and approver either way, so a self-merged PR adds a step without adding safety; the test gate above is the real safety net.

**CI failure handling**: the same Build Run watches the GitHub Actions run and iterates until green, bounded by the cost/time guardrail ([05](05-cost-guardrails-mechanism-not-numbers.md)) — not a fire-and-forget push that can leave main broken until a future run.

**Secrets/config**: Built Application code reads all runtime config/secrets via env vars only, documented via a committed `.env.example`; zero hardcoded values. Real values are injected by the ticket-12 deploy pipeline's secrets flow.

**Dependencies**: default to free/OSS/self-hostable packages, mirroring the cost-consciousness/open-source lean applied to every other decision in this spec; avoid paid SaaS SDKs unless a task genuinely requires one.

**Commit messages**: no mandated format (e.g. Conventional Commits) — nothing in this spec reads commit messages programmatically, and there's no human changelog audience to serve.

**Out of scope for this ticket**: runtime logging/error-handling conventions for Built Application code — deferred entirely to [Visibility standard design](13-visibility-standard-design.md), so app-level and Build-Run-level observability get decided together rather than split across two tickets.
