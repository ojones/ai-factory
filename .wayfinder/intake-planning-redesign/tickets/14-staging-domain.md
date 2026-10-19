---
title: Staging domain
type: task
status: open
assignee:
blocked_by: [13-planning-process.md]
---

## Question

Make the Staging domain (`staging/`, STEP 3.1 to 3.2) a folder that does: stage the app (repo from the Starter, Fly app, flag-service connection, `Intake: <factory>#<parent>` marker) and verify infrastructure (CI green, healthy deploy, flag round trip, Preview Token path, declared secrets, smoke test), triggered by `proceed-with-change` on a `kind: staging` child instead of `ready-for-staging`. `app-staging.yml` and `stage.sh` change accordingly; `stage.sh` comments the repo link on the parent instead of closing it; the one-app-through-staging check counts open staging children in progress. Remove every `ready-for-staging` reference. Unit test everything that is not shell (the staging checklist, the concurrency count, trigger conditions); test `stage.sh` with a dry-run mode where possible.

## Added context

Source plan: "Changes 3". Riskiest ticket; consider splitting the shell and workflow part from the Python part. The planner's staging child body is produced by the Planning domain (ticket 09); this ticket owns what staging does with it.

**Moved here from ticket 03:** change the New App Intake form text (no `ready-for-staging`; submitting starts planning; the first child stages the app) in the same commit that makes it true. Also rename `Handoff` and `Idempotency` wording in ARCHITECTURE.md's Deployment provisioning section from the Target notes to plain statements.
