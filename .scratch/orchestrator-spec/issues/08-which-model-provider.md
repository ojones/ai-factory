Type: research
Status: resolved

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

## Answer

**DeepInfra, serving `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo`** (Qwen3-Coder-480B-A35B-Instruct, Apache 2.0, Alibaba's Qwen team): cheapest confirmed per-token price for a model specifically RL-trained for long multi-turn tool-calling agentic loops (not a retrofitted chat model); leads open-weight models on an agentic tool-use benchmark (68.7, beating Claude Sonnet 4's 65.2) while competitive on SWE-bench Verified (69.6%); 262K/1M context window; Apache-2.0 and served identically on multiple other providers (low lock-in); flat concurrency-based rate limit (200 concurrent/model) suits a long, modest-concurrency unattended Build Run.

Runner-up: **Together AI, same model** — ~20% higher output-token price ($1.20 vs $1.00/M) and rate limits that ramp with sustained traffic (weaker fit for a cold overnight start), but has a stronger documented account-level billing API (`/v1/billing/usage`) — the natural fallback if independent spend reconciliation beyond per-call token accounting is ever needed.

Also ruled out: DeepSeek V4 Pro (higher raw SWE-bench but 3-4x the price, not agent-RL-trained), Kimi K3 (documented cross-vendor tool-calling fidelity problems, steep reliability drop under load, 10-15x output price), GLM-5.3 (inconsistent benchmark story), OpenRouter (5.5% fee + auto-fallback undermines pinning a model), Groq (no top-tier open coding model served).

Full findings with citations: see branch `research/model-provider`, file `.scratch/orchestrator-spec/research/model-provider.md` (commit 06a7e7f).
