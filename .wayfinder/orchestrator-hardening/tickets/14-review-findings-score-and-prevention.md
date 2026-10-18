---
title: Score review findings: when to release anyway, when to retry, and when to file a Factory ticket that prevents them
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

A reviewer asked to find problems will nearly always find a couple. If a release needs a review with zero findings, nothing ships; if every finding sends the coder back for another round, runs burn money, stall and hit the round limit over trivia. Today the gate is binary on the reviewer's own severity label: any `blocking` finding stops the release and goes back to the coder, and `minor` findings never block and are only recorded (up to `MAX_MINORS` per run) as learning issues. The label comes from the model, so how strict the gate is depends on how the reviewer happens to phrase things. How do we decide, from a score rather than a label, between three outcomes: **release** with the findings noted, **retry** (another coder round), or **file a Factory ticket** so the same finding is prevented at creation time next time?

Decide:

(a) **A score per finding and per review.** Inputs to consider: category (correctness, security and data safety, requirement not met, flag misuse, test quality, style and naming, duplication), the evidence it cites (a failing check or a repro versus an opinion), whether a deterministic check could have caught it, whether it recurs across rounds and across apps, and whether a user could ever see it. Output: one number or a small set of bands, produced by the Orchestrator from structured fields, not by the model's own verdict (the principle already applied to `derive_review` and `derive_test`).

(b) **The release rule.** For example: release when no finding scores above a threshold and the tester passed, whatever the count of low-scoring findings; retry only for findings above the threshold that the coder can act on; never retry for style. Where do the thresholds sit, are they per build kind (first build, update, retirement), and do they tighten when the app has a lot of users or data (it has none today).

(c) **Prevention is the primary tool.** Style and quality findings should not exist because a **style guide and lint rules** already prevent them (ticket 15). A finding that a linter, formatter, type rule, template default or test could have caught becomes a Factory ticket (the fix-type ladder in the learning loop: deterministic check, then Starter Template default, then prompt text, then Orchestrator change), and the reviewer's rubric is told not to raise anything a check already covers. Decide when a repeated finding crosses into "file the Factory ticket" (the first occurrence, as the learning loop does today, or a count of distinct runs), and how to avoid the same finding being filed again.

(d) **What the reviewer is for.** If style and mechanical quality move to checks, the reviewer's job narrows to what only judgement can find (requirements the change does not meet, security and data risks, flag misuse, tests that assert nothing). Measure whether that cuts rounds and noise.

(e) **Calibration from real runs.** There is data: Build Run reports and App State issues record rounds, blocking findings and minors per run; the dashboard (`factory-data`) aggregates them. Score the historical findings, see how many runs would have released earlier and what would have escaped, and set the thresholds from that and from the reviewer seeded-bug fixtures (`agents/smoke`), not from a guess.

## Added context

- Today's mechanics: `derive_review` returns `(clean, blocking, minor)` and a run releases only when `clean`, the tester passed and CI and deploy are green for the same SHA (`release_gate`). Findings carry `severity`, `summary`, `evidence` and optional `file`, `line`, `requirement`, `suggested_fix`, `repro`. The reviewer rubric (`agents/prompts/reviewer-rubric.md`) decides what is blocking versus minor in prose.
- The learning loop already turns recurring minor findings into `factory-learning` issues and proposes Factory pull requests, auto-merged only when they are additive lint or formatter config in the Starter Template. The Starter now ships ESLint and Prettier (ticket 09), so there is something to tighten.
- Evidence from runs: reviews have often been clean in round 1 while the tester drove the extra rounds, so measure before assuming the reviewer is the main source of retries.
- The owner's stated aim: use style guide and linting as the primary tool for review findings, and score whether to retry a release or create a Factory ticket.
- Relates to tickets 07 (tester fixtures), 08 (benchmark protocol) and 15 (style guide and lint agent).

## Reframed (2026-10-14)

By the time this was picked up, much of the question had been answered by other work: the reviewer runs before the push (so a blocked review costs one call and a coder round, not a CI run, a deploy and a test), the tester's failures are classified by code (`test_impact`: only a helper-observed failure of existing behaviour is a regression), and minor findings and both Agents' `improvements` already reach the retrospective, which files them with a duplicate check. What was left, and is decided below: (1) a computed band for each reviewer finding, (2) a release and retry rule that stops sending the coder things it cannot fix, and (3) moving the review checks that need no judgement out of the reviewer. Part (e), thresholds calibrated from history, is parked: there are only a handful of real runs on one app, so the dashboard has to collect more first. Calibration needs the payoff metric (cost and rounds per accepted change), which is still unspecified on the map.

## Resolution (2026-10-14)

(a) **A band per finding, from structure.** Every reviewer finding now carries a `category` (`correctness`, `security`, `data_safety`, `requirement_not_met`, `flag_misuse`, `test_quality`, `style`, `duplication`, `other`) and an `evidence_kind` (`repro`, `cited`, `opinion`). `banded_findings` decides the band: a finding the reviewer called blocking blocks only if its category can block (not `style`, `duplication`, `other`) and it has a repro, or a cited file and line; otherwise it is minor and the reason is recorded in `downgraded`. A band is never raised: a minor finding stays minor whatever its fields. A finding without the structure is refused and the reviewer is asked again (the same path as a missing findings list), so a label is never trusted alone and a missing field never fails open. Not used: whether a user could see it, and cross-run recurrence, which needs the counting that is not built.

(b) **The release and retry rule.** The release gate is unchanged (CI green, deploy healthy, tester passed, reviewer clean, same SHA); what changed is what costs a round. A reviewer finding costs one only if it is blocking after banding. A tester check goes to the coder only if it was seen to **fail**. A check that was `blocked` or `not_run` cannot be fixed by the coder, so the tester looks again at the same deployed commit (`limits.test_retries`, default 1), and a run that still cannot verify stops as `needs_human` with the unverified checks named, instead of spending coder rounds until the round limit. Thresholds are the same for every build kind (a first build, an update, a retirement); tightening them with user count is parked, since the apps have no users or data.

(c) **Prevention.** Findings that checks could catch are still prevented by checks, which is ticket 15 (not started, and no longer blocked by this one). The learning loop already files the first occurrence as a Factory suggestion and no longer opens a second issue for a reworded repeat. When to file after N distinct runs needs recurrence counting, which is not built. The reviewer's rubric no longer asks for style or naming, and now says what the Orchestrator checks itself.

(d) **What the reviewer is for.** The Orchestrator now makes the two flag checks that need no judgement (`flag_findings`, always minor): a flag no code outside the tests reads, and a flag description with no issue reference. The rubric no longer asks for them, nor for retirement leftovers, which the coder's commit check already rejects. The reviewer keeps what only judgement finds. Whether this cuts rounds or noise is a measurement for later.

(e) **Calibration.** Parked, as above. The reviewer smoke test now uses the real schema and the real banding (`agents/smoke/run.py`), and has not been rerun with a model, so the seeded-bug detection rate under the new rules is unmeasured.

Built and unit-tested (INV-04 rewritten, INV-46): `banded_findings`, `flag_findings`, `failed_checks`, the `test_retries` loop, the schema and prompt changes. Not run live.
