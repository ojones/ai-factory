Type: grilling
Status: resolved
Blocked by: 08

## Question

Given the provider/model chosen in [Which API provider + open-weight model](08-which-model-provider.md) and its billing/usage API, how should the Orchestrator track spend against a cap during a Build Run and what should happen on breach (hard stop mid-run vs. refuse to start the next step), per the mechanism required in [Cost guardrails decision](05-cost-guardrails-mechanism-not-numbers.md)?

## Answer

**Scope**: the cap covers LLM token spend only — not GitHub Actions runner minutes or other metered calls (e.g. a Fly deploy). Token spend is the dominant, unpredictable risk (an Agent can loop); everything else is comparatively small and already bounded by the test-gate/iteration design in [11](11-coding-standards-content.md).

**Tracking mechanism**: every DeepInfra chat-completion response already returns a precomputed `usage.estimated_cost` field (confirmed in DeepInfra's own API docs). The Orchestrator sums this field across every LLM call made during the Build Run and compares the running total to the per-run cap before allowing the next turn — no separate pricing math, no polling DeepInfra's account-level `/payment/usage` endpoint for enforcement (that endpoint remains useful only for retrospective auditing, not live enforcement).

**Breach behavior**: checked after every LLM call. Once the running total would exceed the cap, the current turn is allowed to finish cleanly (never a mid-call abort — risks interrupting a git operation or leaving a half-written file), and the next turn is simply refused.

**Provider-side backstop**: each Build Run is issued its own scoped API credential (a JWT with an embedded max-USD spending limit, per DeepInfra's auth docs) set equal to that run's own configured cap — a second line of defense that mirrors the Orchestrator's own check in case its local tracking has a bug. Preferred over a single shared long-lived key with a coarser monthly `key-limits` cap, since the Orchestrator already has the per-run cap figure in hand for its own tracking and minting a scoped credential with the same number costs nothing extra. Note: DeepInfra has no documented low-balance alert/webhook — this backstop is a hard per-key ceiling, not a notification.

**Linkage**: the accumulated `estimated_cost` total is exactly the figure surfaced as "cost spent" in the [Build Run Summary/Report](13-visibility-standard-design.md). A breach is one of the two outcomes that triggers that ticket's failure-notification GitHub Issue ("budget exhausted before CI went green," distinct from a hard crash).
