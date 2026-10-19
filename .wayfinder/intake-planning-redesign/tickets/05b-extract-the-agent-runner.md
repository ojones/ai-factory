---
title: Extract shared/agent_runner.py
type: task
status: open
assignee:
blocked_by: [05-shared-kernel-and-renames.md]
---

## Question

Behaviour-preserving. Move the Agent runtime out of `build_run.py` into `shared/agent_runner.py` as one `AgentRunner` object with a small interface: start an Agent for a role with a single-model scoped credential limited to what is left of the cap (`Budget`, `mint`), run it with a whitelisted environment and, under `limits.agent_isolation: user`, as the Agent account (`agent_command`, `prepare_agent_user`, `isolation_self_check`, `run_isolation_probes`), kill it by process group when its event stream stalls or the timeout passes (`run_watched`, `kill_agent`, `silent_too_long`), read its spend and context numbers (`collect_usage`, `take_usage`, `summarize_token_usage`), recognise the provider-out-of-balance and spending-limit refusals (`ProviderBlocked`, `spending_limit_hit`, `scan_for_provider_block`), and return its JSON output file with the validated-retry rules (`agent_json`, `json_problem`). The planner, the Build Run's Agents and the retrospective Agent (`mint_agent`, `agent_user`, `record_agent_spend` in `retrospective.py`) all use it. Split it into files by responsibility inside `shared/` only if it exceeds what one reader can hold; tests move with the code.

## Added context

Split out of ticket 05 on 2026-10-19: about 800 lines of `build_run.py` are used by `BuildRun`, `State` and the Report, so this needs the characterization tests first (INV-01, INV-09, INV-20, INV-32, INV-34, INV-45 already cover its behaviour; keep them passing unchanged in meaning). Required before the Retrospective ticket and the planning-process ticket, which both start Agents. Keep `AgentRunner` free of any domain import (`boundary_test`). No behaviour change.
