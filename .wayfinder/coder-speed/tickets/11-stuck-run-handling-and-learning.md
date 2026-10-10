---
title: Stuck runs alert the user and feed learning
type: grilling
status: closed
assignee: ojones
blocked_by: []
---

## Question

When a Build Run hits the round cap, the Orchestrator should alert the user and also record why it got stuck and what would prevent it next time (self-learning). What is recorded (finding patterns, coder misses, prompt or template gaps), where (repo file, GitHub issue), how the alert reaches the user, and who or what turns a recorded cause into a prompt or template change? The cap today ends in a needs_human outcome.

## Added context

From "Make findings concrete": if the reviewer exhausts the rounds and something is still blocking, the coder should stop and the Orchestrator should be alerted. A log of it, kept somewhere durable, should let us fix the cause for all future Managed Apps, treating a stuck run as a chance to improve the whole orchestration system.

## Resolution

Decisions: the record is an issue in ai-factory; analysis is deterministic facts plus a post-mortem agent; the agent's fix goes out as a PR.

Built (`orchestrator/postmortem.py`, a new workflow step after `finalize`, `if: always()`, never fails the run):
- **Alert:** unchanged. A non-clean ending already opens an issue in the Managed App repo and comments on the Intake issue.
- **Facts:** outcome, per-round blocking findings, which recurred across rounds, time and cost per stage, written as the artifact `postmortem-facts.json`.
- **Issue:** one `factory-learning` issue per distinct failure in ai-factory. The title carries a fingerprint (outcome plus recurring findings, rewording-tolerant), so a repeat comments on the open issue instead of opening a new one.
- **Post-mortem agent** (`agents/prompts/postmortem.md`, role `postmortem` in `profiles.yml`): names a category (prompt, template or orchestrator gap, spec ambiguity, model limit, infra) and makes the smallest generalizing change in the Factory checkout; nothing for infra, spec ambiguity or model limit.
- **PR:** the Orchestrator, not the agent, keeps only changes under `agents/`, `templates/starter/`, `orchestrator/` and the docs (never `.github/` or protected template files), runs the unit tests, commits to `learning/run-<id>`, pushes with `FACTORY_PAT`, and opens a PR for human review. The agent holds no credential.

Verified: facts, fingerprint and path-guard unit tests (46 pass). Not verified: any of the GitHub or agent parts. They need `FACTORY_PAT` to be able to push branches and open PRs in ai-factory (unknown), `openhands`, and a real stuck run. Failure of any of them only skips that part. The agent runs outside the Build Run's cost cap, bounded by `postmortem_timeout_minutes: 15`.

Related: [Minor findings become issues and template fixes](12-minor-findings-to-issues-and-templates.md) should reuse the `factory-learning` label and this triage flow.
