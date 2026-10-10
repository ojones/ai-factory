# Agent configuration

The editable configuration for the Orchestrator's Agents, kept apart from the architecture and Standards so it can be tuned over time without touching them. Roles and stage order are defined in [ARCHITECTURE.md](../ARCHITECTURE.md#agents-and-build-run-stages); this directory holds only what is expected to change.

- [profiles.yml](profiles.yml): which model, endpoint, and prompt each role uses, plus the run limits (review rounds, default and maximum cost cap, credential lifetime). Switching a role's model or the provider is an edit here and nowhere else.
- `prompts/<role>.md`: one role prompt per Agent (`coder`, `reviewer`, `tester`, `pipeline`, `postmortem`), each edited independently.

The Build Run workflow reads these files from ai-factory at run time. They are never copied into a Managed App repo, so the coder can't edit its reviewer's instructions, and changes apply to the next Build Run without touching any Managed App.

A model is only eligible for a role if DeepInfra (or whichever provider is configured) serves it on an OpenAI-compatible API and returns per-response `usage.estimated_cost`, because the cost guardrail depends on that field. Smoke-test a new model against it before pinning.

## Prompt placeholders

The Build Run replaces `{{name}}` placeholders before invoking OpenHands.

| Role | Placeholders |
|---|---|
| coder | `app_name`, `round`, `task`, `findings_path` |
| reviewer | `app_name`, `base_sha`, `head_sha`, `verdict_path` |
| tester | `app_name`, `app_url`, `head_sha`, `report_path`, `previous_report`; env `PREVIEW_TOKEN` |
| pipeline | `app_name`, `head_sha`, `failure_run_url`, `diagnosis_path`, `context_dir` |
| postmortem | `facts_path`, `result_path`, `categories` (run by `orchestrator/postmortem.py`, not the Build Run) |

## Output contracts

Each non-coder role writes JSON the Orchestrator parses; the Orchestrator never trusts a role's own conclusion field over the evidence.

- **reviewer** (`verdict_path`): `analysis`, `findings[{severity: blocking|minor, summary, evidence, file, line, requirement, suggested_fix, repro}]` (the last five are best-effort; empty when not applicable), `verdict`, in that key order. The Orchestrator derives the verdict from the findings.
- **tester** (`report_path`): `passed`, `results[{flag, check, passed, evidence, repro}]` (`repro` is best-effort). The Orchestrator derives `passed` from `results`.
- **pipeline** (`diagnosis_path`): `category: code|workflow|infra|flaky`, `summary`, `fix_request` (string or null), `retry_recommended`.

`agents/smoke/` holds fixtures that replay known-buggy diffs through the reviewer; rerun it after changing the reviewer prompt or model.
