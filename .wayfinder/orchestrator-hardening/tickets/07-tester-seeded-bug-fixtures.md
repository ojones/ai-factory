---
title: Tester seeded-bug fixtures
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

The reviewer has seeded-bug fixtures (`agents/smoke/`, four known bugs, run in CI via `smoke-reviewer-model.yml`); the tester has none, so nothing shows it fails a broken app. Build fixtures the tester must fail: small apps or recorded deployments with a known defect in a flagged feature (wrong status code, missing validation, flag reachable without the Preview Token, kill switch not honoured). Measure the tester's detection rate across trials, and decide whether mutation testing is worth adding as an independent check on agent-written tests.

## Added context

- `agents/prompts/tester.md` works in about 12 tool calls with batched `curl` and throwaway data; the speed work (coder-speed ticket 16) trimmed it, so detection rate is the number to protect.
- `agents/smoke/run.py` and `expected.json` show the harness shape to reuse; `agents/replay/` replays real recorded tasks.
- The advice says tests written by the same model are not independent proof; this ticket is how we check the tester is.
- Test bed (needs a tester-only replay harness first): commit a deliberately buggy flagged feature to a frozen copy of `ojones-todo` and measure whether the tester fails it. Evidence so far: the tester's report was rejected for invalid JSON once on a correct run; it needs a script-written report (fixed in 60ab6b0).

## Result (2026-10-12): built, measured, and the tester misses half of what is seeded

Harness: `agents/smoke-tester/` (`run.py`, `fixtures.json`, `base/notes.ts`; unit-tested in `orchestrator/test_smoke_tester.py`). The real tester prompt and model run against a local copy of the Starter Template serving a flagged notes API, behind a stub GrowthBook (kill switch on), with a git checkout holding a "previous release" and a head commit. One correct version and seven with exactly one seeded bug. `--validate` (no model, free) proves the correct version passes an independent checker and each bug trips exactly the check it should. Scored the way the Orchestrator reads a report (`derive_test`, so INV-28 applies).

First run, `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo`, 2 trials per fixture, 16 runs, **$1.82**:

| fixture | caught | note |
|---|---|---|
| good (control) | 0 false alarms in 2 | |
| wrong-status (POST 200 not 201) | 2/2 | |
| flag-leak (no gate) | 2/2 | |
| no-blank-check | 1/2 | |
| wrong-order | 1/2 | |
| id-zero (boundary) | 0/2 | |
| lenient-id (`1abc`, hard) | 0/2 | |
| unobservable (audit-log line) | 1/2 | expectation debatable: the code does log it, so a pass on code evidence is defensible |

Overall detection 7/14 = 50%; every catch was for the right reason; no false alarms. Cost per run $0.05 to $0.20, runs up to 17 minutes.

Reading: the tester finds gross faults (wrong status, flag leak) and misses edge cases. The prompt tells it to cover "one invalid input and one boundary" of its own choosing, so it does not systematically check each error case the spec lists (blank text, id 0, `1abc`). Next: change the prompt to derive one check per behaviour the spec states, and re-measure with the same harness (about $1.6 for the six bug fixtures and the control at 2 trials). Mutation testing stays an option for the tests the coder writes, which is a different question.

## Second measurement (2026-10-12): spec-driven prompt, and what the numbers can and cannot say

Changed `agents/prompts/tester.md` step 2 to build the checklist from the spec itself: one check per stated behaviour, every named error case, and the usual malformed forms (missing, wrong type, blank, zero, negative, trailing characters). Added two held-out bugs the prompt was not written against (`no-trim`, `dup-ids`). 18 runs, $1.89.

| | before (v1 prompt) | after (v2 prompt) |
|---|---|---|
| the same six bugs | 6/12 | 6/12 |
| held-out `no-trim`, `dup-ids` | not measured | 2/4 |
| false alarms on the correct app | 0/2 | 0/2 |
| checks per run | about 6 | 14 to 16 |

A follow-up of 3 kept-report runs (wrong-status, id-zero, dup-ids) caught 2 of 3 for real; the third was a run where the tester could not execute `curl` at all, so every check was `not_run`. **That run had been scored as a catch**; the harness now scores a run with no real failure as *inconclusive* and leaves it out of the detection rate. The loose "right reason" patterns (`0|zero|...` matched the 0 in 200) were tightened.

What this supports: the tester finds gross faults reliably and edge cases about half the time; the new prompt makes it far more thorough (it now tries zero, negative, decimal) without a measurable gain in detection and without a regression beyond noise. What it does not support: any claim that one prompt is better than the other. The same bug (`wrong-status`) went caught, missed twice, caught across rounds. Two trials per fixture cannot separate a prompt effect from run-to-run variance; at least 5 per fixture (about $4.5 for the full set) would.

Candidate fixes not yet tried: a deterministic check of expected against observed status in the report (so the Orchestrator, not the model, decides that 200 is not 201); a stronger tester model (the harness is the benchmark for that, ticket 08); and diagnosing why a tester sometimes cannot run `curl`.

## Third measurement (2026-10-12/13): two cheaper open-weight tester models on the edge-case bugs

The tester model had never been screened (it was the default, `Qwen3-Coder-480B`). Chosen as the two cheapest of the plausible agentic candidates on DeepInfra: `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B` ($0.50/$2.20 per million tokens) and `Qwen/Qwen3.5-397B-A17B` ($0.45/$3.00). Both passed the eligibility checks (tool-call round trip, structured output, `estimated_cost`). Screened on the four bugs the current model mostly misses, 3 trials each, with the v2 (spec-driven) prompt, plus the correct-app control. A run in the middle was lost when the DeepInfra account ran out of balance (HTTP 402 "You need positive balance"); those cells were rerun after a top-up.

| bug | current tester (v2 prompt) | Nemotron-3-Ultra | Qwen3.5-397B |
|---|---|---|---|
| blank text accepted | 1/2 | 3/3 | 3/3 |
| id 0 answers 404 | 0/2 | 2/3 | 3/3 |
| `1abc` read as id 1 (hard) | 1/2 | 3/3 | 3/3 |
| duplicate ids | 1/3 | 3/3 | 1/3 |
| **total** | **3/9 (33%)** | **11/12 (92%)** | **10/12 (83%)** |
| control (correct app) | 2/2 correct | 3/3 correct | 3/3 correct |
| cost per run | about $0.11 | $0.147 | $0.184 |
| median time per run | n/a | 394 s | 495 s (some runs spanned a laptop sleep) |

Every catch was for the right reason and no run was inconclusive. The two candidates miss different things (Nemotron the id `0` boundary once, Qwen3.5 the duplicate ids twice), which is more likely noise at n=12 than a stable difference; they are not distinguishable from each other. Both are clearly better than the current model on these bugs. Nemotron is also cheaper and faster, and from a lab (NVIDIA) different from the coder and reviewer (DeepSeek) and from the current tester (Qwen), so independence is kept.

Not yet measured for either candidate: the gross-fault fixtures the current model already catches (`wrong-status`, `flag-leak`), `wrong-order`, the held-out `no-trim`, and `unobservable`. A model that is better on the hard cases but worse on the easy ones would be a bad trade, so confirm those before switching `roles.tester.model` in `agents/profiles.yml` (and update the tester line in ARCHITECTURE.md). Estimated cost of that confirmation: 18 runs, about $2.7.

## Decision (2026-10-13)

The confirmation run was skipped by decision: `roles.tester.model` in `agents/profiles.yml` is now `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B`, on the strength of 11/12 against 3/9 on the hard bugs with no false alarms. Known gap: not measured on the easy and held-out bugs. Revert is one line (the old id is in the comment). Watch the first real Build Runs for the tester missing something the old one caught, and run `agents/smoke-tester/` over the remaining fixtures when convenient (about $2.7).


## Resolution

Resolved: the tester seeded-bug benchmark in `agents/smoke-tester/` (stub GrowthBook, a notes API with seeded bugs, judge and summary) measured two models; Nemotron-3-Ultra caught 11 of 12 on the edge-case bugs and is now the tester. Mutation testing was not added; api-check (INV-30) makes the status-code class of bug mechanical.
