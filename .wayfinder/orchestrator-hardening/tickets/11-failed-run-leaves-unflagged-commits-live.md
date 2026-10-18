---
title: A failed run leaves its unflagged commits live
type: grilling
status: closed
assignee:
blocked_by: []
---

## Question

Every push to `main` deploys. For a flagged change that is safe: the code is dark until the Orchestrator releases it, and it releases only after a clean pass. For a change with no flag (a retirement, a refactor, a dependency bump, a first build) the deploy *is* the release. So when a Build Run ends without a clean pass (`round_limit`, `needs_human`, `budget_exhausted`, `stuck`, a crash), the commits it pushed stay on `main` and stay live. What should happen to an unflagged run's commits when the run fails: revert them automatically (a revert commit on `main`, which is itself a deploy), hold them behind a deploy gate until the run passes, or leave them and tell the owner loudly? Also, should a change set that may not add a flag still get any kind of dark-until-verified path?

## Added context

- Seen for real on `ojones-todo` (2026-10-12): the failed `delete-todo-endpoint` retirement run re-gated the live `DELETE /api/todos/:id` behind a brand-new flag that was never released. The commits deployed, and DELETE has returned 404 in production since, with no alert beyond a `needs_human` Issue.
- The Orchestrator is the only thing that pushes, so a revert is possible: `git revert` the run's range from the recorded `commits` list in the Report and push. Risks: the revert deploys too; a revert of a partly good run loses good work; concurrent runs for one app are serial (`queue: max`) so the range is unambiguous.
- Related: the post-release watchdog only watches after a *release*; a deploy of an unflagged change has no equivalent watch. `STANDARDS-FEATURE-FLAGS.md` says unflagged changes "go live on deploy with the Test Gate as their only pre-live gate".
- Test bed: `ojones-todo` DELETE is currently dark and can be restored by releasing `retire-delete-flag`, or by a corrective Update Intake.

## Resolution

Decision: revert on failure (plan A), plus a fix request issue for every bad ending. Preview-environment deploys (plan B) are deferred until an app has real users, because they break the "production is the only test environment" principle and cost infrastructure.

Built, and unit-tested against real git repositories (`orchestrator/test_revert.py`, `test_finalize.py`, `test_fixrequest.py`); **not yet run on GitHub**:
- `finalize` puts `main` back where the run started with one new commit that restores the starting tree (`revert_main_to_base`; history kept, nothing force-pushed), waits for that commit's deploy and `/api/health` (`wait_for_revert_deploy`), and records `revert` in the Report and Summary. It skips if `main` has moved on since the run's last push, never reverts a good ending or a `watchdog_disabled` run, and reports a failed revert (an audit finding, rule A-07). `limits.revert_failed_runs`: `all` (default), `unflagged`, `off`.
- `finalize` now also saves the final state (audit, revert) back to `state.json`. It did not before, so the post-mortem never saw the audit and the audit-violation lessons could not fire from a real run.
- `orchestrator/fixrequest.py`: one issue per bad ending (what happened, what was done automatically, automated analysis, numbered requirements), routed by the post-mortem's cause to the Factory (`factory-fix-request`, picked up by the Factory Run), to the app as an unstarted Update Intake, or as information; one open issue per Intake, repeats comment. The Factory route uses the Factory Run, not the app planner, because the planner plans changes to Managed Apps.
- Decided afterwards: an app-side fix request is not left for a person. It is an Update Intake that **starts itself** (`proceed-with-change` added with the PAT), carrying the failure, earlier attempts' findings, how to approach the retry, requirements, the original request and its cost cap. A retry never stops to ask: the planner turns a blocking question into a recorded assumption (the most conservative reading). Bounded by `fix_request_max_attempts` (2); after that the next is filed unstarted with `needs-human`. A Factory-side fix request never starts itself (a PR a person merges).
- INV-25, INV-26 and INV-27 in `docs/invariants.md`.

Not covered, and still open: the window while a run is in progress, when users can see an intermediate version; a runner that dies before `finalize` (detectable later as "`main` moved with no clean ending"); and the first live run of any of this.

## Live result (2026-10-12, `ojones-todo`, request #77 "count endpoint" under a $0.08 cap)

Worked end to end with no person involved: attempt zero ran out of money in its tester → `main` reverted to the exact starting tree (`f48860eb`, checked), redeploy healthy → a fix request filed → **started itself** (`proceed-with-change` added with the PAT) with a **doubled cap ($0.16)**, the failure, the earlier attempt and a clean requirement list → released in one round for $0.11, watchdog clean, `GET /api/todos/count` answers 200. Git history shows add, revert, add, revert, add.
Bugs the live runs found and fixed on the way: a spent-out stop was reported as `needs_human` (now `budget_exhausted` at 90% of the cap); the post-mortem called that a prompt gap and sent the retry to the Factory (a budget ending now routes to the app); the retry pasted the post-mortem's Factory-side requirements into the app request; a retry with the same money would have failed the same way (now doubled, up to the ceiling); a tester marked a check `passed` while writing that it could not observe it (now `not_run`, INV-28).
Not yet seen live: the attempt bound stopping a chain at attempt 3 (unit-tested, INV-27); the `info` route; a revert that itself fails; `revert_failed_runs: unflagged`.
