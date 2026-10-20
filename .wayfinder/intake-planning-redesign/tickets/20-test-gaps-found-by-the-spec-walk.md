---
title: Test gaps found by walking the spec
type: task
status: open
assignee:
blocked_by: []
---

## Question

Close the two steps of `docs/flow-spec.md` that have no direct test, found by ticket 18: STEP 4.8 (Diagnose pipeline failure: the Pipeline Agent reads CI logs and the coder fixes) has tests of the fix loop (`ship_code_test`, `run_test`) but none of the diagnosis itself or of its retries (`pipeline_retries`, `pipeline_fix_attempts`); STEP 2.6 (Route the child by kind) is two workflow conditions (`update-app-intake.yml` skips a staging child, `app-staging.yml` starts only one) with only the staging half covered by INV-57. Write a unit test for each (the workflow conditions can be read as YAML like INV-57 does; the diagnosis through `ship_code` with a fake Pipeline Agent), and add the invariants to the table if they are rules.

## Added context

Also not seen live and worth a line each when a run happens to hit them: 4.2 (a ride-along flag), 4.10 (a retest), 4.11 (a regression rollback), 5.3 to 5.7 (flag retirement and dark-broken), 7.1 to 7.6 and 8.x (the failure-to-fix path), 6.7 (the first scheduled production-feedback run after the change). Those are ticket 17's, not this one's.
