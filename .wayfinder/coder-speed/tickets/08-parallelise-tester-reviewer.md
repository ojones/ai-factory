---
title: Run tester and reviewer in parallel
type: grilling
status: closed
assignee: ojones
blocked_by: [01-measure-where-time-goes]
---

## Question

Do tester and reviewer depend on each other or on the coder's final test run? If not, run them concurrently, and decide how their findings merge.

## Note from the measure ticket

`review_and_test` in `orchestrator/build_run.py` already runs the reviewer and tester concurrently, so the remaining question is only whether they can start before the coder's push or CI. Likely close or shrink this ticket.

## Resolution

Closed without a build. The reviewer and tester already run concurrently once Deploy is green (`review_and_test`). Starting the reviewer earlier, during CI and Deploy, would save about 10 seconds with the single-call fast reviewer, and a pipeline fix changes the commit, so the early review would be redone and the budget split complicated. The tester needs the deployed app and is the slower of the two, so it sets the round time. The lever is the tester's speed: see [Tester speed](16-tester-speed.md). If the exploring reviewer ever becomes the default again, revisit.
