---
title: Test gaps found by walking the spec
type: task
status: resolved
assignee: ojones
blocked_by: []
---

## Question

Close the two steps of `docs/flow-spec.md` that have no direct test, found by ticket 18: STEP 4.8 (Diagnose pipeline failure: the Pipeline Agent reads CI logs and the coder fixes) has tests of the fix loop (`ship_code_test`, `run_test`) but none of the diagnosis itself or of its retries (`pipeline_retries`, `pipeline_fix_attempts`); STEP 2.6 (Route the child by kind) is two workflow conditions (`update-app-intake.yml` skips a staging child, `app-staging.yml` starts only one) with only the staging half covered by INV-57. Write a unit test for each (the workflow conditions can be read as YAML like INV-57 does; the diagnosis through `ship_code` with a fake Pipeline Agent), and add the invariants to the table if they are rules.

## Added context

Also not seen live and worth a line each when a run happens to hit them: 4.2 (a ride-along flag), 4.10 (a retest), 4.11 (a regression rollback), 5.3 to 5.7 (flag retirement and dark-broken), 7.1 to 7.6 and 8.x (the failure-to-fix path), 6.7 (the first scheduled production-feedback run after the change). Those are ticket 17's, not this one's.

## Resolution

Both steps have direct tests now, and each is an invariant. STEP 4.8: `build_run/ship_code_test.py` (`Diagnosis`) drives `BuildRun.pipeline` with a fake Pipeline Agent: a green pipeline costs no diagnosis; a flaky or infrastructure failure is re-run with `gh run rerun --failed` and then passes; re-runs stop at `pipeline_retries`; a code failure goes to the coder with the Agent's fix request; coder fixes stop at `pipeline_fix_attempts`; a workflow problem or a code failure with no fix request stops for a person; a failed health check is diagnosed from the app's Actions page. INV-62. STEP 2.6: `staging/route_child_test.py` reads both workflows and checks that the text they match is what `render_marker` writes for a staging child, that App Staging takes only that and the Build Run start takes the rest, and that a `benchmark` child goes to neither; INV-61. The flow spec's "Verified by" column is updated. Still not seen live: a pipeline failure.
