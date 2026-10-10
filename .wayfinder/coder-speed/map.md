---
label: wayfinder:map
title: Make the coder faster
---

## Destination

The coder's per-run wall time is measurably lower on the replay cases with no drop in pass rate, and the adopted changes from the ten ideas below are made in the repo.

## Notes

- Execution override: tickets may carry out the adopted change (edit prompts, profiles, orchestrator) as part of resolving, not only decide.
- Judge every change on the replay harness (`agents/replay`) against a baseline: pass rate first, then time, tool calls, cost.
- Origin: ChatGPT review of the OpenHands blog (https://chatgpt.com/share/6ac9a9a8-be34-83e8-9159-ff5cc985e1bb) plus a ten-item list of ideas.
- Tracker: local markdown. Tickets in `tickets/`; blocked_by lists ticket filenames; claimed = assignee set.
- Related: STANDARDS.md, agents/profiles.yml, agents/prompts/coder.md.

## Decisions so far

- [Measure where coder time goes](tickets/01-measure-where-time-goes.md): per-invocation wall and model time added to stage usage, log lines and the run summary; unverified against real OpenHands state.
- [Cut review rounds](tickets/02-cut-review-rounds.md): cap 4, fix rounds blocking-only with targeted checks.
- [Make findings concrete](tickets/03-concrete-findings.md): optional detail fields passed inline to the coder; blocking always blocks; the earlier evidence downgrade is reversed.
- [Give the coder fast tools](tickets/06-fast-tools.md): check / test:changed / test:file / verify scripts in the Starter Template; new apps only.
- [Reconsider the coder model](tickets/05-coder-model.md): bar is equal pass rate and 30% faster; fast model round 1, `fix_model` after; two-stage evaluation (smoke screen, then replay) ticketed.
- [Reuse the environment across rounds](tickets/04-reuse-environment.md): checkout already reused across rounds; `npm ci` now runs once after the clone with a minimal env, not as coder turns.
- [Make template build and test faster](tickets/09-faster-build-and-test.md): Docker layer cache, no duplicate build in Test Gate, Test Gate and Build in parallel with a deploy gate; orchestrator ignores skipped deploy runs. Unrun on GitHub.
- [Run tester and reviewer in parallel](tickets/08-parallelise-tester-reviewer.md): already parallel; starting the reviewer earlier saves ~10s, not worth it. Opened Tester speed instead.
- [Tester speed](tickets/16-tester-speed.md): ~12 tool-call budget, batched curl scripts, fix rounds re-check failures plus a fast regression pass using the previous report.
- [Condense context on long runs](tickets/07-condense-context.md): measurement already exists; no condenser until a run shows a coder peak over 100k; prompt now keeps tool output small.
- [Stuck runs alert the user and feed learning](tickets/11-stuck-run-handling-and-learning.md): factory-learning issue per stuck run (fingerprinted), post-mortem agent, validated PR for review. Unrun on GitHub.
- [Minor findings become issues and template fixes](tickets/12-minor-findings-to-issues-and-templates.md): unresolved minors become app-repo suggestions and ai-factory learning issues; post-mortem agent considers each immediately; findings now saved on clean passes. Unrun on GitHub.
- (pre-map, no ticket) `agents/prompts/coder.md` already tightened: targeted tests first, no reinstall unless needed, scoped staging, short report. Uncommitted and unmeasured.

## Not yet specified

- Parallel coders on independent subtasks with merge via tests, if ticket "Split big tasks" says yes.
- An Orchestrator-side check of protected files, flag state and test results, instead of trusting the coder's report.
- Moving detailed procedures (debugging, test conventions) into on-demand skills.

- A faster model for the tester (ride on the coder smoke screen) and a scripted per-flag request plan.

## Out of scope

- Changing the reviewer model (already moved to a fast single-call reviewer, issue #41).
