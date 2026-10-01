Type: research
Status: open

## Question

Given inference will be consumed via a pay-per-token API rather than self-hosted (see [Model serving decision](02-model-serving-api-not-selfhosted.md)), which provider and which specific open-weight model should the Factory pin?

Compare candidates (e.g. Together AI, Fireworks, DeepInfra, OpenRouter, Groq, and any other provider serving open-weight models by the token) against:
- Price per input/output token
- Open-weight model catalog quality for coding tasks (benchmark performance on coding/agentic benchmarks, not general chat quality)
- Context window size
- Tool-calling / function-calling reliability (needed by the Agent harness)
- Rate limits and any constraints on long unattended sessions
- Billing/usage API availability (needed to meter spend for the cost guardrail mechanism)

Recommend one provider + model pairing, with the runner-up and why it lost.
