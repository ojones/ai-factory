---
title: Give the pre-push review and the deployed test their own round budgets
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

One counter, `limits.review_rounds` (default 4), now covers two very different costs. A round is one review, one test pass (only if the review was clean) and one fix commit, so a blocked review spends one model call and a coder round, while a deployed test spends a push, CI, a deploy and the tester. The stuck detector (`stuck_rounds`) and the `round_limit` ending read the same scoreboard. Should the two have separate limits (for example a cheap review limit and a tighter test limit), which of them does the stuck detector watch, what does each ending say, and how does this interact with `test_retries` and the run's cost cap?

## Added context

- Where it lives: the round loop in `BuildRun.run` (`orchestrator/build_run.py`), `stalled` and `scoreboard_entry`, `limits.review_rounds`, `limits.stuck_rounds` and `limits.test_retries` in `agents/profiles.yml`; ARCHITECTURE.md stages 2 to 4; INV-19 and INV-46.
- Before the pre-push review existed, one counter was reasonable because every round deployed. Now a run can spend all its rounds on reviews that never push, or never reach the tester at all.
- The evidence from earlier runs was that the tester, not the reviewer, drove the extra rounds; measure that with the payoff metric (ticket 19) before choosing numbers.
- Keep the unit tests of the round loop (`RoundLoop` in `orchestrator/test_build_run.py`) as the place to prove the new behaviour.

## Resolution (2026-10-14)

Decided as a default and built; no live run. Not put to the owner as separate questions, because the cost data (1 round $0.20, 2 rounds $0.41, 3 rounds $0.94) points one way.

- **Two limits.** `review_rounds` (4) still bounds all rounds, which is cheap for a blocked review (a model call and a coder round, no push). New `test_rounds` (2) stops the run for a person once that many deployed tests have *failed*, since each costs a push, CI, a deploy and a tester pass. Only one fix gets a second deployed test.
- **Counting.** Only a deployed test with failed checks counts. Blocked reviews do not use it up, and unverified checks retested under `test_retries` do not count either.
- **Ending.** Same `round_limit` outcome with a message naming the failed deployed tests, so fix requests, the dashboard and the stuck count need no change.
- **Stuck detector.** Unchanged: it watches the whole scoreboard, so it still catches identical rounds whether they were reviews or tests.
- **Cost cap.** Unchanged; `test_rounds` is the cheaper, earlier stop in front of it.
- Revisit the numbers with ticket 19's payoff metric.

Unit-tested in `RoundLoop`.
