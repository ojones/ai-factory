---
title: Reconsider the coder model
type: grilling
status: closed
assignee: ojones
blocked_by: [01-measure-where-time-goes]
---

## Question

The reviewer got ~100x faster by moving to a smaller model. Which faster/smaller coder candidates on DeepInfra should be replayed, what pass rate and time do we require, and do we keep the 480B as fallback for later rounds?

## Resolution

- **Bar:** a candidate replaces the 480B Qwen coder only with equal pass rate (build + tests green and reviewer-clean) and at least 30% faster.
- **Use:** fast model first, big model after a failed round. Built: an optional `fix_model` on the coder in `agents/profiles.yml`; `model_for` in the Orchestrator uses it for every coder attempt after round 1 (fix rounds and pipeline fixes), and `model` for round 1. Unset means no change in behavior. Tests added.
- **Evaluation, two stages:** a coder smoke screen of small deterministic tasks to cull weak or slow candidates (good at spotting broken models, poor at separating close ones), then a coder replay on recorded tasks for the top two. Both are builds, so they are tickets: [Coder smoke screen](14-coder-smoke-screen.md) and [Coder replay for the top two](15-coder-replay-top-two.md).
- **Not decided:** the candidate list; it comes from the smoke screen ticket.
