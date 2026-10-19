---
title: Extract shared/agent_runner.py
type: task
status: resolved
assignee: ojones
blocked_by: [05-shared-kernel-and-renames.md]
---

## Question

Behaviour-preserving. Move the Agent runtime out of `build_run.py` into `shared/agent_runner.py` as one `AgentRunner` object with a small interface: start an Agent for a role with a single-model scoped credential limited to what is left of the cap (`Budget`, `mint`), run it with a whitelisted environment and, under `limits.agent_isolation: user`, as the Agent account (`agent_command`, `prepare_agent_user`, `isolation_self_check`, `run_isolation_probes`), kill it by process group when its event stream stalls or the timeout passes (`run_watched`, `kill_agent`, `silent_too_long`), read its spend and context numbers (`collect_usage`, `take_usage`, `summarize_token_usage`), recognise the provider-out-of-balance and spending-limit refusals (`ProviderBlocked`, `spending_limit_hit`, `scan_for_provider_block`), and return its JSON output file with the validated-retry rules (`agent_json`, `json_problem`). The planner, the Build Run's Agents and the retrospective Agent (`mint_agent`, `agent_user`, `record_agent_spend` in `retrospective.py`) all use it. Split it into files by responsibility inside `shared/` only if it exceeds what one reader can hold; tests move with the code.

## Added context

Split out of ticket 05 on 2026-10-19: about 800 lines of `build_run.py` are used by `BuildRun`, `State` and the Report, so this needs the characterization tests first (INV-01, INV-09, INV-20, INV-32, INV-34, INV-45 already cover its behaviour; keep them passing unchanged in meaning). Required before the Retrospective ticket and the planning-process ticket, which both start Agents. Keep `AgentRunner` free of any domain import (`boundary_test`). No behaviour change.

## Resolution (2026-10-19)

Behaviour unchanged. `ruff check` clean, 506 tests OK (3 skipped; 12 new in `shared/agent_runner_test.py`), every flat module still imports as a script, `boundary_test` passes. `build_run.py` is 2,243 lines (was 2,617). Not committed.

**Moved out of `build_run.py` into `shared/`, one file per responsibility:**
- `run_stops.py`: `BudgetExhausted`, `ProviderBlocked`, `NeedsHuman`.
- `http_client.py`: `request` (was `http`).
- `provider.py`: the provider address, empty-account detection (`provider_blocked_text`, `scan_for_provider_block`), `spending_limit_hit`, `provider_check`, `model_status`.
- `spend_budget.py`: `Budget`.
- `agent_process.py`: `agent_command`, `run_isolation_probes`, `isolation_problems`, `kill_agent`, `silent_too_long`, `run_watched`.
- `agent_usage.py`: `summarize_token_usage`, `merge_usage`. `agent_output.py`: `adopt_misplaced_file`, `json_problem`, `load_json`, and the new `retry_prompt`. `console.py`: `log`.
- **`agent_runner.py`:** `AgentRunner` (model per role and round, the whitelisted environment, `run` for one invocation, reading the conversation's usage) and `json_output` (the retry loop). It is built from what it needs (config, budget, directories, Agent user, a limits check, a spend callback), not from the Build Run.

**In the Build Run.** `BuildRun.invoke` only renders the prompt for this run and calls `runner.run`; `agent_json` calls `json_output` with callbacks for restoring the tree and recording the failed Agent's stage; the runner is made right after the budget (`make_runner`). Tests that patched the old names now patch the shared modules. The model-per-round and environment-whitelist (INV-01) tests moved to the runner's own tests.

**New tests** cover `run` (credential minted for the role's model, limits checked first, a stalled or timed-out Agent, the Agent-user home and pid file, an empty account stops the run, conversation usage read back and kept) and `json_output` (first try, retry told what was wrong, two bad tries, a spent credential gets no second attempt, a rejecting check).

**Left for later tickets:** the retrospective Agent's own start-up code (`mint_agent`, `run_agent` in `retrospective.py`) still has its own flow built on the shared pieces (`run_watched`, `Budget`); it moves onto `AgentRunner` in the Retrospective ticket (10). The planner needs nothing: it already runs through `BuildRun.agent_json`.
