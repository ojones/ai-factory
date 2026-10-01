Type: grilling
Status: resolved

## Question

Should the spec define concrete numeric cost caps (e.g. "$5/Build Run") now, or just the mechanism a Build Run must have (a budget cap + hard stop + behavior on breach), leaving concrete numbers as a config decided at build time?

## Answer

Spec the mechanism only, not hardcoded numbers. The numbers are a tuning knob that will change with model pricing and usage patterns; the spec requires that a cap exists and is enforced, not a frozen dollar figure. Mechanism design is deferred to [Cost guardrail enforcement design](../issues/14-cost-guardrail-design.md).
