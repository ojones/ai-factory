---
title: Coder smoke screen
type: task
status: open
assignee: ojones
blocked_by: []
---

## Question

Build a small set of coder smoke tasks (small, deterministic, with tests that pass or fail) in `agents/smoke` style, and a runner that runs the coder prompt with a given DeepInfra model against each and reports pass/fail, wall time and cost. Which 4-6 candidate models (faster and smaller than the 480B Qwen, served on an OpenAI-compatible API that returns `usage.estimated_cost`) go through it, and which two survive? Output: the two finalists and the numbers.

## Progress: built, not yet run

Built `agents/smoke-coder/`: four tasks on the Starter Template (add a route, fix a bug, a flagged update, a multi-route todo API), each with hidden acceptance tests and a reference solution, plus `run.py`, which runs the real coder prompt per model/task/trial and scores: commit made, no protected file changed, `npm run check` and `npm test` (with the acceptance tests) pass. It reports pass rate, median seconds, model-time, calls and cost per model, with each model's speed against the first listed (the baseline).

Verified without a model: `python3 agents/smoke-coder/run.py --validate` shows each task's acceptance tests fail on the seed, the scorer says "no commit" for an untouched checkout, and a committed reference solution passes. Not verified: a real run. This shell has no `openhands` and no `DEEPINFRA_API_KEY`, and the `base_state.json` cost and latency fields are assumed from the OpenHands SDK.

Candidates, chosen from DeepInfra's live `/models` list as faster or smaller than the 480B: DeepSeek-V4.1-Flash, Qwen3.8-Flash, GLM-5.3-Flash, Qwen3.5-35B-A3B, gpt-oss-120b-Turbo, MiniMax-M3. Whether each serves tool calls and returns `usage.estimated_cost` (required by the cost guardrail) is unchecked: run `MODEL=<id> python3 agents/smoke/run.py` (T1, T2) first.

To close: run `MODELS=Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo,<candidates> TRIALS=2 python3 agents/smoke-coder/run.py` and pick the two finalists (pass rate at least equal to the baseline, fastest).
