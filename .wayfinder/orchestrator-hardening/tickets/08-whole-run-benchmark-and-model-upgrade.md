---
title: Whole-run benchmark and model-upgrade protocol
type: research
status: resolved
assignee:
blocked_by: [07-tester-seeded-bug-fixtures]
---

## Question

The last model switches were decided on two replay tasks and a smoke screen. Define a fixed benchmark of about 10 Intakes (first builds and updates, some with seeded traps) that exercises the whole Build Run, a protocol for any model or prompt change (run the suite, compare acceptance pass rate, rounds, cost and time against a baseline, only then switch), and a fallback model or provider for when DeepInfra or a pinned model ID is unavailable. Research what a minimal, cheap version looks like and what it costs per full pass.

## Added context

- Models, prompts and limits are config in `agents/profiles.yml`; the provider `base_url` is already swappable, which also allows a stub endpoint for deterministic orchestration tests.
- Coder and reviewer are now the same model, which makes independent evaluation more important.
- `agents/smoke-coder/` and `agents/replay/` are the existing partial benchmarks; the tester fixtures from the previous ticket feed this one.
- Pin `openhands` (the workflow installs it unpinned) as part of the protocol.
- Progress outside this ticket: `openhands` is now pinned in `agents/openhands-version.txt` (1.16.0, the latest for Python 3.12 and the version installed locally; the version earlier Build Runs used is unknown). An experiment showed the CLI works against any OpenAI-compatible endpoint set in `LLM_BASE_URL`, so a stub model can stand in for DeepInfra, and that OTLP tracing crashes this version (see ARCHITECTURE.md: Visibility).
- Test bed: `ojones-todo` is not a clean baseline (every Intake mutates it). Freeze a git bundle of it at a known commit, as `agents/replay/data` does for earlier apps, and replay the fixed Intakes from that. Real costs seen so far: $0.05 first build, $0.10-0.18 per small update.
- Progress from ticket 07: `agents/smoke-tester/` is a ready, hermetic tester benchmark (local app, stub GrowthBook, seeded bugs, scored by `derive_test`) that a model-upgrade protocol can reuse; a full pass costs about $1.8 at 2 trials with the current tester model.

## Resolution (2026-10-14)

Built, with the owner's goal that the evals make model swaps routine as models get cheaper, faster and more specialised. `docs/benchmark-protocol.md` is the protocol; `orchestrator/benchmark.py` with `agents/benchmark/{suite,rules}.json` is the suite (seven Intakes: a flagged route, an edge-case validation, an internal refactor, a named flag retirement, an ambiguous spec, refusals of payments and a pasted secret) and the oracle (outcome plus `api_check` scenarios, decided by code); the manual `Benchmark` workflow runs a candidate (a branch with the candidate models) through the real Build Run against a disposable bench app reset to a frozen commit, and compares with `baseline.json` (INV-41). Cost of a pass is about $0.60 to $3.20 and 1.4 to 3 hours (I first estimated $3 to $4.50 for eight Intakes; the real run costs of $0.1 to $0.6 give the lower figure). Fallback: a `fallback_model` per role with a one-token check before any work, and a nightly model canary that keeps one `model-drift` issue open. Not done: the bench app has not been staged (`agents/benchmark/bench-app-spec.md`), no baseline exists, and the suite has never run, by the owner's choice (run it when a swap is pending). Not covered by the suite: first builds, UI changes, multi-change-set plans, the post-mortem Agent. `openhands` is pinned (`agents/openhands-version.txt`).
