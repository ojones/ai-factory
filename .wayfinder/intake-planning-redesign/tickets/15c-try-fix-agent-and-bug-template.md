---
title: Try Fix Agent and the bug template
type: task
status: resolved
assignee: ojones
blocked_by: [15b-failure-events-and-retrospective-verdicts.md]
---

## Question

Build step 7.6. Add the `try_fix` role to `agents/profiles.yml` (model, fallback, prompt `agents/prompts/try_fix.md`, `try_fix_cost_cap_usd`) and the Agent call in `try_fix/write_bug.py` using the shared Agent runner with its own capped credential. Its one job: from one event with a `fix` verdict (cause, target and reason already decided) write `how_found`, `root_cause`, `what_it_takes[]` and checkable `requirements[]`; it never decides the cause or target and never plans or splits work. `try_fix/validate_bug.py` rejects empty or uncheckable requirements, more than `planner_max_criteria`, and any secret value, and falls back to the deterministic text (`failure_text`) when the Agent fails or its output is rejected. `try_fix/render_bug.py` and `.github/ISSUE_TEMPLATE/bug.yml` render the bug template (What happened, How it was found, Root cause, What it would take to resolve, Target, Failure and solution log) under the headings `plan_run.read_intake` already reads (`App name`, `What should change?`), so the planner needs no change for a bug Intake. Add the prompt to the prompt registry and invariant NEW-B (it only writes, its output is validated or replaced). Unit tests: validation and fallback, render round-trips through `read_intake`, the Agent is never given the PAT.

## Added context

Reverses ticket 15's choice that the Orchestrator writes fix text; the Orchestrator still writes the fallback. Owner's rule: each Agent has one job (Retrospective diagnoses, Try Fix writes the ticket, the planner plans, the Build Run builds). The model is unmeasured; note it like the planner's.

## Resolution

Built. The Try Fix Agent and the bug template exist and are tested; nothing files a ticket yet (15d).

- **The Agent** (`try_fix/write_bug.py`, role `try_fix` in `agents/profiles.yml`, prompt `agents/prompts/try_fix.md`): one model call with no tools, not a coding Agent run, because it only writes text. It gets the decision already made (target, cause, reason), the event and the run's facts, and returns `how_found`, `root_cause`, `what_it_takes` (1 to 4) and `requirements` (1 to `planner_max_criteria`). The prompt says it does not decide the cause or target and does not plan. Credential: a scoped single-model key limited to `try_fix_cost_cap_usd` (0.25), minted by `write_bug.mint`; the spend goes to the ledger (`record_spend`). The shared call is `shared/model_call.py`, which `retrospective/judge_events.py` now uses too. Model `openai/gpt-oss-120b` (the planner's), unmeasured.
- **Validation and fallback** (`try_fix/validate_bug.py`): empty fields, a wrong count, a repeated, too-short or vague requirement ("improve", "consider", "as appropriate"), and anything secret-shaped are problems. Any problem, a failed call, no key or no role makes the Orchestrator write the same four fields itself (`write_bug.fallback`, reusing `failure_text.requirements` for a run's failure), and the fallback passes its own validation. `validate_bug.scrub` takes secret-shaped text out of an event's evidence before it reaches the model, the fallback or the ticket.
- **The template** (`try_fix/render_bug.py`, `.github/ISSUE_TEMPLATE/bug.yml`): What happened, How it was found, Root cause, What it would take to resolve, Requirements (numbered), Target, Failure and solution log, as `####` sections inside the form's "What should change?" so `plan_run.read_intake` reads a bug exactly like an Update App Intake (tested through it). A Factory bug uses the same text without the form. The hidden `<!-- bug:KEY -->` marker is the event's key; in an Intake it goes first, because the form's last section runs to the end of the body (found by the test). The form carries `bug` and `update-app-intake`, so a person can report one too.
- INV-59 holds it. Not done: the model's tickets are unmeasured on real events; the Agent is not called by anything until 15d.
