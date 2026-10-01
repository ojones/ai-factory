Type: grilling
Status: resolved

## Question

Per [map.md](../map.md)'s "Not yet specified" list: now that every research and Standards-content ticket in this spec pass has resolved, how should the spec actually be packaged/published as a handoff-ready deliverable — a single consolidated document, or multiple Standards files (e.g. one per concern: coding, deployment, visibility, cost guardrails, feature flags)? Where does it live, and what's the relationship between this `.scratch/orchestrator-spec/` working material (tickets, map, research branches) and whatever gets handed off to a later build effort?

## Answer

**Two-tier split**, matching the Destination's own wording: `ARCHITECTURE.md` for decisions about how the Orchestrator itself is built (consumed once by whoever builds it) and `STANDARDS.md` for Agent-facing rules (operationally re-read by every Build Run) — collapsing these into one document would blur a distinction the spec already draws for itself.

**File structure**, all at repo root (not a new `docs/` folder — `GLOSSARY.md` already sets the precedent of a top-level reference doc):
- `ARCHITECTURE.md` — one file: harness, model/provider, compute platform, deploy target, IaC approach, cost-guardrail enforcement mechanism, plus the Orchestrator-side provisioning halves of deployment/visibility/feature-flags.
- `STANDARDS.md` — a short index linking the four files below, so there's one canonical entry point (what the Starter Template's `AGENTS.md` points back to).
- `STANDARDS-CODING.md`, `STANDARDS-DEPLOYMENT.md`, `STANDARDS-VISIBILITY.md`, `STANDARDS-FEATURE-FLAGS.md` — split per concern, since each is read by a different part of a Build Run.

**Splitting mixed-content tickets**: several source tickets (12, 13, 18) contain both Agent-facing rules and Orchestrator-build content in one Answer. Each got split across both documents by the test "does a Built Application's own code need to follow this, or is this how the Orchestrator is built/operates" — e.g. ticket 12's container/registry/workflow-split rules went to `STANDARDS-DEPLOYMENT.md`, while its GitHub App + Fly token provisioning flow went to `ARCHITECTURE.md`. Ticket 14 (cost guardrail) is entirely `ARCHITECTURE.md` — nothing in it is something a Built Application's own code follows.

**Writing style**: each rule stated prescriptively with a 1-2 sentence rationale, cross-referencing its originating ticket for the full reasoning, runner-ups, and citations — not fully self-contained.

**Relationship to `.scratch/orchestrator-spec/`**: kept as-is, permanently, as the audit trail. `.scratch/` being a disposable-working-notes directory governs where the *deliverable* lives (promoted to repo root), not whether the deliberation record is worth keeping — deleting it would throw away the "why" a future swap (e.g. the deploy-target swappability requirement) will want to consult. Not promoted into formal `docs/adr/` entries either — ~20 tickets already read like ADRs; converting them would be ceremony without benefit.

`README.md` updated to link to all three.
