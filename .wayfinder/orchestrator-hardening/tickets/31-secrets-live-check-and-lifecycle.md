---
title: Prove the secrets path live, and build its scan and lifecycle pieces
type: task
status: open
assignee:
blocked_by: []
---

## Question

Ticket 16 built the first slice of the secrets workflow without running it. Prove it once with a throwaway secret name, and build what the first slice left out: (1) the live check, on a scratch app: an Intake that needs `THROWAWAY_TEST_KEY` stops `awaiting_secret` with the command on the Intake; after `gh secret set THROWAWAY_TEST_KEY -R owner/app` and the label again, it builds, and the deploy step copies the value to Fly and masks it in the log. Confirm the Orchestrator's PAT can run `gh secret list` on an app repo (it may need the Secrets read permission) and that `toJSON(secrets)` does not print the value. (2) A scan of the Report, the Agents' event streams and the artifacts for secret shapes before they are uploaded, redacting a hit, and a `secret-leak` issue naming the kind and location, never the value. (3) A daily model-free pass that lists each app's secrets older than 90 days and secrets no longer in `secrets.json`, commenting on one open issue per app. (4) Do not start a retry whose errors point at authentication or a missing secret: the story comment asks the owner to rotate. (5) A line in the teardown skill that deleting the repo and destroying the Fly app removes the secrets.

## Added context

- The decisions and defaults are in the Resolution of [13-secrets-management-workflow.md](13-secrets-management-workflow.md); what was built is in [16-build-the-secrets-workflow.md](16-build-the-secrets-workflow.md). INV-48 to INV-50.
- The live run is a real Build Run (about $0.30); it can share the run in ticket 21.

## Live results (2026-10-15)

Proven: the planner declared `THROWAWAY_TEST_KEY` and the run ended `awaiting_secret` with the exact command and the hidden marker on the Intake (the Orchestrator's PAT can run `gh secret list`); after `gh secret set` and the label again, the build proceeded, a coder commit that listed an undeclared name was rejected, the declared name was listed statically in the deploy workflow, and the live app returned `configured: true` and never the value, so the deploy step delivered it to Fly. Not proven: that the value is masked in the deploy log (look at the deploy run's log), and items (2) to (5) are not built. The throwaway secret is still set on the app; delete it with `gh secret delete THROWAWAY_TEST_KEY -R ojones/ojones-todo` when finished.
