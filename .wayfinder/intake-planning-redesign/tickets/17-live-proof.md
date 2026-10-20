---
title: Live proof
type: task
status: open
assignee: ojones
blocked_by: [14-staging-domain.md, 14b-new-app-intakes-are-planned.md, 15-try-fix-domain.md, 15b-failure-events-and-retrospective-verdicts.md, 15c-try-fix-agent-and-bug-template.md, 15d-file-the-bug-intake-and-fix-for.md, 16-bugs-domain.md]
---

## Question

Prove it live, once each, ride-along only: an Update App Intake on the bench app end to end (STEP 2.1, 2.4, 2.5, 4.1, 6.3, 6.4); a new app end to end (3.1, 3.2, then flagged children); a failing child that gets a bug Intake with `fix_for`, planned to one child behind the same flag, and resumes when it closes (6.2, 7.6, 7.1, 7.4); a production error on a released flag that files a regression bug Intake with a fresh flag (8.3, 8.4); a warning the Retrospective judges `record` that files nothing. Then retire `limits.planner_enabled`.

## Added context

Source plan: "Verification" items 4 and 5. Do not spend dedicated runs on housekeeping; say what was not seen. Record cost and surprises.

## Live proof so far (2026-10-20)

Pushed to `main` and ran a New App Intake, `factory-bench` (ai-factory#140), end to end. Seen live: STEP 1.1, 2.1, 2.4, 2.5, 2.6, 3.1, 3.2, 4.x, 4.13, 6.1 to 6.4, 5.1 and 5.2.

- Planning filed two children, #141 (`kind: staging`, started) and #142 (flagged, `waiting-on-plan`, blocked by #141); the staging child verified all six checks and closed; the advance started #142; it was released behind `factory-bench.feature.issue-142` (named after its own number) in one review pass for $0.13 of a $1.50 cap; the parent closed with its last child; the retrospective posted. `/api/health` answers 200. Total model spend about $0.35, of which four planning attempts $0.18.
- Planning needed three fixes first, each found by a live attempt and pushed: the validator wanted a requirement link on the staging change set (it has none); the new-app planner asked blocking questions about the Starter Template (twice: which flag client, then the route file) because its working directory was empty, so it now reads a copy of the Starter and the prompt forbids questions the code answers. These are exactly what a unit test could not have found.
- Not seen yet, and not run (the owner approved only the new-app proof): an Update App Intake on the bench app (2.1 to 2.5, 6.3, 6.4 with an update, retirement ride-along 4.2); a failing child that gets a bug Intake with `fix_for`, one child behind the same flag, and resumes (6.2, 7.6, 7.1, 7.4); a production error on a released flag filing a regression bug (8.3, 8.4) and a warning judged `record`; the watchdog (4.13 watched ten quiet minutes, its trip not seen). `limits.planner_enabled` is not retired yet.
- Oddities to watch: the planner numbered its change sets CS-0 and CS-1; it assumed routes live in `backend/src/routes` (the Starter has `app.ts`), harmless here; the Plan job runs the full unit suite first, adding minutes before the planner starts.
