---
title: Coder smoke screen
type: task
status: closed
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

## First real pass (1 trial per cell, 3 runs at a time, so timings are noisy)

| Model | Passed | Median wall | Avg cost/run | Avg calls |
|---|---|---|---|---|
| Qwen3-Coder-480B (baseline) | 4/4 | 96 s | $0.11 | 25 |
| DeepSeek-V4.1-Flash | 3/4 | 75 s (22% faster) | $0.012 | 11 |
| Qwen3.8-Flash | 3/4 | 148 s (slower) | $0.009 | 13 |

- **No candidate clears the bar** (equal pass rate and at least 30% faster) on this evidence.
- **The baseline is not reliable either:** an earlier pass (before a harness fix) had it fail 2 of 4 on the same tasks, so n=1 per cell cannot separate models. More trials are needed before any cut.
- **Model time is 75-90% of wall time** for every model (for example the baseline's t4: 152 s of 172 s). Tools, npm and waiting are minor, so the lever is a faster model or fewer calls per task, not the environment.
- DeepSeek-V4.1-Flash makes about half the calls at a tenth of the cost; its one failure was the todo task's id and list assertions. Qwen3.8-Flash makes few calls but is slow per call, and once stopped after 4 calls with no commit.
- Harness fixes made along the way (in `agents/smoke-coder/run.py`): per-model working directories, cost computed from tokens and DeepInfra's public prices (OpenHands reports 0), and failure reasons that show the failing assertions. `response_latencies` and `calls` are confirmed against real OpenHands state.

Next: more trials (TRIALS=3) on the baseline and DeepSeek-V4.1-Flash, plus the remaining candidates, before choosing finalists.

## Resolution: smoke screen done (7 models screened, top two repeated)

Single trials of every candidate, then repeats of the two best. Combined results (4 tasks per trial):

| Model | Passed | Median wall | Avg cost/run | Avg calls | Notes |
|---|---|---|---|---|---|
| Qwen3-Coder-480B (baseline) | 6/8 | 79 s | $0.113 | 26 | failed t1 once and t3 once, so it is not reliable either |
| DeepSeek-V4.1-Flash | 9/12 | 59 s (25% faster) | $0.010 (11x cheaper) | 11 | t1-t3 pass 9/9; fails the todo task's distinct-id assertion 3/3 |
| GLM-5.3-Flash | 8/12 | about 180 s | $0.016 | 11 | 4/4 on one trial, then 4/8 on repeats; latency swung 52-274 s |
| Qwen3.8-Flash | 3/4 | 148 s | $0.009 | 13 | slow per call; one run stopped without a commit |
| Qwen3.5-35B-A3B | 3/4 | 102 s | $0.16 | 33 | failed the flag task; costs more than the baseline |
| gpt-oss-120b-Turbo | 3/4 | 179 s | $0.24 | 50 | one no-commit; one task took 95 calls |
| MiniMax-M3 | n/a | n/a | n/a | n/a | timed out once and took 331 s on the easiest task; stopped |

- **Finalist: DeepSeek-V4.1-Flash.** Equal pass rate to the baseline (75%) at 25% less wall time and a tenth of the cost, just under the 30% bar. Its one failure is systematic, not random: the todo task's distinct-id assertion failed in all 3 trials, which points at a repeatable habit (for example how ids are generated) worth looking at in the replay.
- **No second finalist.** GLM-5.3-Flash looked best on one trial and fell apart on repeats; nothing else beat the baseline on reliability or speed. This is why single trials plus repeats on the leaders was the right shape.
- **Model time is 75-90% of wall time**, so the lever is the model and calls per task, not the environment.
- **n is small** (8 baseline runs, 12 DeepSeek), so the 25% figure could land on either side of 30%.
- profiles.yml is unchanged. The existing `fix_model` option fits the finalist: DeepSeek-V4.1-Flash for round 1 and the 480B Qwen for fix rounds would cover its todo-style misses at the cost of an extra round when it misses.
