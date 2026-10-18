---
title: Stage the bench app and record the first whole-run benchmark baseline
type: task
status: open
assignee:
blocked_by: []
---

## Question

Ticket 08 built the whole-run benchmark and the model-swap protocol and nothing has run: the bench app `factory-bench` is not staged and there is no accepted baseline. The owner wants it run only when a model swap is pending, so this ticket waits for that trigger. When a cheaper, faster or more specialised model is worth trying, stage the bench app (`agents/benchmark/bench-app-spec.md`), run the suite for the current models to record the baseline, then run the candidate and compare under `agents/benchmark/rules.json`. A pass costs about $0.60 to $3.20 and takes 1.4 to 3 hours.

## Added context

- Protocol and rules: `docs/benchmark-protocol.md`, `orchestrator/benchmark.py`, `agents/benchmark/`; the manual `Benchmark` workflow is dry-run by default.
- The suite was written for the old pipeline order; check the tasks and their expected outcomes still hold with the reviewer before the push, the new `needs_human` stop for unverifiable checks, and the retrospective after every run before trusting a baseline.
- Model fallbacks and the nightly canary already exist (INV-41).
