---
title: Keep every Build Run under $1
type: research
status: resolved
assignee:
blocked_by: []
---

## Question

The owner's goal: every Build Run costs less than $1. What does a run cost now, where does the money go, and which changes get the expensive tail under $1 without lowering quality? Decide (a) what the target means (every run, or the 90th percentile; whether the retrospective Agent's spend counts), (b) whether the goal is also enforced, for example by lowering the default per-run cap from $2 to $1 and deciding how a retry's doubled cap fits, (c) how to make the tester, which dominates the expensive runs, cheaper, (d) how to see where money goes, since part of it is not recorded today, and (e) what else is worth trimming.

## Added context

**What runs actually cost (the spend ledger, 2026-10-13 and 14).** 32 Build Runs on `ojones-todo`: mean $0.30, 30 of 32 under $1, two over ($1.11 and $1.16, both ending badly); the third most expensive was $0.97. The retrospective Agent (recorded as `postmortem` in the ledger, 7 entries): mean $0.10, max $0.21, and it now runs after every run, so each run's total with it is about $0.10 higher. The $1 to $2 once quoted for a template-sync run was the default cap ($2), not typical spend; a typical run is about $0.30. The goal is therefore about the tail, and about keeping the typical run from creeping up.

**Where the money went in the three expensive runs** (stage costs from each run's Report):

| Run | Outcome | Total | Tester | Coder | Planner | Reviewer |
|---|---|---|---|---|---|---|
| 38337364025 | stuck, 3 rounds | $1.11 | $0.587 (3 passes) | $0.453 (5 invocations) | $0.065 | $0.006 |
| 38573153785 | nothing_to_release, 3 rounds | $0.97 | $0.716 (3 passes) | $0.196 (6 invocations) | $0.050 | $0.006 |
| 38447198656 | needs_human, round 1 | $1.16 | not staged | $0.022 | $0.089 | $0.002 |

- The tester is 53% to 74% of an expensive run, because each fix round runs it again; its prompt says to re-run every check that passed.
- The reviewer is about $0.002 to $0.006 per review, so reviewing is not where the money goes.
- The planner is $0.05 to $0.09 and the coder $0.2 to $0.45 over several invocations.
- **The third run is not explained by its stages.** The stages sum to about $0.11, so about $1.05 of the $1.16 is not attributed to any stage. The run ended `needs_human` in round 1, and an Agent attempt that fails does not get a stage, so it was probably failed tester or coder attempts. Confirm from that run's event streams. Whatever it was, the Report cannot show where money goes in a failed run, which is (d).

**Levers to consider**
- Tester (the biggest): on a fix round re-run only the checks that failed, plus a small fixed smoke set, instead of every passed check; cap its tool calls harder (the prompt aims for about 15); a cheaper tester model, judged against the seeded-bug benchmark (`agents/smoke-tester/`, ticket 07) so detection does not drop (the current tester is `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B`); and avoid the extra tester pass that `limits.test_retries` can add.
- Rounds: every round after the first multiplies the tester. The pre-push review (a blocked review costs about $0.006 plus a coder round) and banding findings should already cut rounds; measure it (ticket 19). Separate round budgets (ticket 25) and checks before the reviewer (ticket 26) also act on rounds.
- Coder: 5 to 6 invocations in the costly runs; look at why (rejected commits, protected-file rejections, fix rounds) and at its context size (`context_goal_tokens` is 100,000).
- Enforcement: `limits.cost_cap_usd_default` is $2 and the ceiling for an Intake override is $10 (`agents/profiles.yml`); a run that hits the cap ends `budget_exhausted` and its retry doubles the cap (`fixrequest.raised_cap`), so a $1 cap could make a failing story cost $1 then $2. Decide whether the goal should cap a first attempt at $1 and what a retry may spend. The daily cap ($10) is unchanged.
- Accounting (d): record the cost of a failed Agent attempt in the Report (as a stage or as `failed_attempts`), so the table above can be built for every run, not only the ones that finished.

**Related:** ticket 19 (the payoff metric: cost per accepted change, which is how to know the goal is met), ticket 24 (the benchmark that judges a cheaper model), ticket 25 (round budgets), ticket 26 (checks before the reviewer), and the cost guardrails in ARCHITECTURE.md. The data above came from the `factory-ledger` issue (#46) and the `build-run` artifacts of the three runs.

## Findings (2026-10-14): all 32 Build Runs

From each run's Report (the `build-run` artifact), 32 Build Runs on `ojones-todo`, total $9.47, mean $0.30, median $0.14.

| Where the money went | $ | share |
|---|---|---|
| tester | 4.35 | 46% |
| coder | 1.74 | 18% |
| planner | 1.56 | 16% |
| not attributed to any stage (failed Agent attempts) | 1.73 | 18% |
| reviewer | 0.10 | 1% |

- **Rounds drive cost, more than any Agent.** One round (23 runs): mean $0.20. Two rounds (3 runs): $0.41. Three rounds (3 runs): $0.94. Four (1 run): $0.61. The 7 runs with two or more rounds are 22% of the runs and about half of all spend.
- **A tester pass is cheap when it works:** median $0.068, mean $0.113, max $0.306 (22 runs with a pass). So the tester is expensive because it runs once per round and because failed attempts are not cheap, not because one pass is.
- **The unattributed $1.73 is three `needs_human` runs**, one of them $1.04 of a $1.16 run. That run's two tester attempts each ran until their credential ran out ("token spending limit exceeded", 70 and 34 tool steps) and neither wrote a report; at the time the tester got half of what was left per attempt, which is $0.69 plus $0.35. It was the first live ui-check run, before the helper waited for the page to settle; the next ui-check run cost $0.30.
- **Only 3 of 32 runs reached $0.97 or more**; none of the other 29 passed $0.75. The expensive ones are: that failed-tester run, a stuck 3-round run ($1.11, tester $0.59 over 3 passes, coder $0.45 over 5 invocations), and a 3-round `nothing_to_release` run ($0.97, tester $0.72).
- **By outcome:** released mean $0.22 (max $0.48), nothing_to_release $0.29, needs_human $0.42 (max $1.16), stuck $1.11.
- The retrospective adds about $0.10 a run and is recorded in the ledger separately.

**What follows.** The typical run is already well under $1, so the target is the tail, and the tail is rounds and failed attempts, not any single Agent's price. A cheaper tester model or a leaner tester prompt would save little (a pass is about $0.07), so they are not the first lever. The levers that act on the tail: fewer rounds (planner accuracy, ticket 27; round budgets, ticket 25; the pre-push review and banded findings already built), a hard bound on what one Agent and one run can spend, and not paying twice for a failure.

## Built so far

- A failed Agent attempt now gets a stage (`<Role> failed`) with its cost, so the Report accounts for all the spend and the unattributed share goes to zero.
- An Agent that spent its whole credential without writing a usable file is not given a second attempt (it would get a credential of the same size and repeat it); the run stops with the cost named.
- Both are unit-tested (`orchestrator/test_build_run.py`).

## Resolution (2026-10-14)

Decided with the owner, and built where it is code. The tail is rounds and failed attempts, so the work is mostly in other tickets; revisit this one if the 90th percentile stays over $1 once they are done.

(a) **What the target means.** Every run under $1, tracked as a target and not enforced: the dashboard (`orchestrator/dashboard.py`, `COST_TARGET_USD`) shows runs over $1 and the 90th percentile cost, overall and in the daily digest. *Default, not put to the owner:* the retrospective Agent's spend is not part of a run's number (it is a separate ledger line, about $0.10).

(b) **Enforcement.** None beyond the existing caps: the default per-run cap stays $2 (an Intake can override up to the $10 ceiling) and $1 is a goal. The owner chose this over lowering the cap; the cost is that a runaway can still reach $2.

(c) **Per-Agent share of the cap.** Not added (owner's choice): one cap for the run. The tester used to get half of what was left when it ran beside the reviewer and now, running alone, can spend all that remains; a failed attempt is now bounded by not repeating it (below). **A retry's cap:** no doubling. After a `budget_exhausted` run the retry gets the cap the request had, and its guidance says the cap is not raised and to do less in one pass; `fixrequest.raised_cap` and the stored retry cap are gone. A story therefore costs at most the cap per attempt (`fix_request_max_attempts` is 2 retries).

(d) **Accounting (built).** A failed Agent gets a stage, `<Role> failed`, with its cost and attempts, so every dollar in the ledger is attributed in the Report; and an Agent that spent its whole credential without writing a usable file is not given a second attempt, which would only repeat it (`spending_limit_hit`, `agent_json`).

(e) **Other levers.** A leaner tester prompt or a cheaper tester model would save little: a tester pass is median $0.07, so they were not pursued. The levers on the tail are fewer rounds: the pre-push review and banded findings (built), planner accuracy (ticket 27) and round budgets (ticket 25), and measuring it (ticket 19).

Unit-tested: the failed-attempt stage, the no-second-attempt rule, no cap doubling, and the dashboard's target metrics. Not run live.
