---
title: Measure where coder time goes
type: task
status: closed
assignee: ojones
blocked_by: []
---

## Question

Add per-round timing to the orchestrator/replay (wall time, LLM calls, tool calls, time in install/build/test, rounds used) so every later ticket is judged on numbers. What is the minimum instrumentation, and where does it plug in? (HITL or AFK; the code change is carried out here, per Notes.)

## Resolution

Instrumentation lives in `orchestrator/build_run.py`, reusing the existing usage record on each stage, so it flows into the state file and the Build Run summary with no new plumbing:

- `invoke` times each agent invocation (`seconds`, wall clock, summed across retries by `merge_usage`).
- `summarize_token_usage` adds `llm_seconds` from OpenHands' `response_latencies`. Wall minus model time is tool and wait time (install, build, test).
- The log line per invocation and a new "Time (model)" column in the summary show both. LLM call count was already there.
- Test updated in `orchestrator/test_build_run.py`; all 34 pass.

Caveats: the `response_latencies` shape is assumed from the OpenHands SDK and has not been checked against a real `base_state.json`; it falls back to 0, so confirm on the first real run. No per-command split yet (install vs build vs test); add it only if the wall-minus-model figure shows tool time dominates. Replay already prints per-case `secs` for the reviewer path.
