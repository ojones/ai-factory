---
title: Minor findings become issues and template fixes
type: grilling
status: closed
assignee: ojones
blocked_by: []
---

## Question

Minor and unverified findings no longer cause rounds. They should be opened as GitHub issues, picked up later in their own lightly-scheduled task, and used to update the Starter Template (or shared prompts) so the same finding does not recur in any Managed App. Which findings become issues (all minor, or only recurring ones), how are duplicates collapsed, what picks them up and when, and what is the rule for promoting a finding into a template or prompt change?

## Note from the stuck-run ticket

Use the same `factory-learning` label, fingerprint-in-title dedup, and the post-mortem agent's PR path (`orchestrator/postmortem.py`) rather than building a second mechanism.

## Resolution

Decisions: unresolved minor findings go both to the Managed App's own repo and to ai-factory; a potential fix is considered immediately, with no recurrence threshold (the agent must justify that a change generalizes or decline, and a human reviews the PR); pickup is the same post-mortem step at the end of every Build Run.

- **Gap fixed first:** `findings-N.json` was only written when a round failed, so a clean pass lost its minors. `run()` now writes it every round.
- **Managed App repo:** each minor finding still open at the end (up to 5 per run) becomes a `Suggestion:` issue in that app's repo, deduped by title.
- **ai-factory:** one `factory-learning` issue per distinct finding, titled `Minor finding [fingerprint] ...` (rewording-tolerant); a repeat in another app or run comments on it instead.
- **Pickup:** `orchestrator/postmortem.py` now also runs after clean runs that have minors. The post-mortem agent considers them for a generalizing prompt or Starter Template change and the Orchestrator validates and opens the PR as before. A finding whose issue already records a proposed `**PR**:` is not sent to the agent again, so a declined or closed proposal is not retried automatically.
- **Cost:** one agent run (15 minute limit, outside the cost cap) per Build Run that ends with minors or stuck.

Tests added (47 pass). Not verified: the GitHub issue, agent and PR parts, as with the stuck-run ticket.
