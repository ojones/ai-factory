---
title: Live proof
type: task
status: open
assignee:
blocked_by: [14-staging-domain.md, 14b-new-app-intakes-are-planned.md, 15-try-fix-domain.md, 15b-failure-events-and-retrospective-verdicts.md, 15c-try-fix-agent-and-bug-template.md, 15d-file-the-bug-intake-and-fix-for.md, 16-bugs-domain.md]
---

## Question

Prove it live, once each, ride-along only: an Update App Intake on the bench app end to end (STEP 2.1, 2.4, 2.5, 4.1, 6.3, 6.4); a new app end to end (3.1, 3.2, then flagged children); a failing child that gets a bug Intake with `fix_for`, planned to one child behind the same flag, and resumes when it closes (6.2, 7.6, 7.1, 7.4); a production error on a released flag that files a regression bug Intake with a fresh flag (8.3, 8.4); a warning the Retrospective judges `record` that files nothing. Then retire `limits.planner_enabled`.

## Added context

Source plan: "Verification" items 4 and 5. Do not spend dedicated runs on housekeeping; say what was not seen. Record cost and surprises.
