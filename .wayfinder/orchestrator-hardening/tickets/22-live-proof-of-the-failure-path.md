---
title: Prove the failure path, the rollback and approve-retire with a deliberately failing Intake
type: task
status: open
assignee: ojones
blocked_by: []
---

## Question

The failure path has never run live: a flagged change that fails stays dark and is retried on the same issue and flag, the tester's failed checks are noted on the story with the `bug` label, the story is labelled `dark-broken` after the retries, and `approve-retire` files an Update Intake that removes the feature; and the CI rollback of a regression (`rollback-fly.yml`) has only a unit-tested decision. Prove each: file an Intake with contradictory acceptance criteria (for example "return 201 and also 409 for the same valid input") with a low cost-cap override, let it fail and retry twice, add `approve-retire`, and separately dispatch `rollback-fly.yml` for the current commit of `ojones-todo`. What does a pass look like, and what is the cost (a stuck run cost $1.11 on 2026-10-13, so expect about $1 to $3 over three runs, less with a low cap)?

## Added context

- Needs `rollback-fly.yml` in the app: template sync delivers it at night after the change reaches `main`. Dispatching it by hand for the current commit proves the CI half (redeploy and health) with no model.
- A real regression cannot be forced on demand; the decision to roll back stays covered by unit tests plus the hand dispatch.
- Expected cost about $1 to $3 over three runs with a low cap (typical runs are about $0.30; stuck ones have reached about $1.10); covers INV-26, INV-27, INV-39, INV-43 and the `regression` route in `fixrequest.py`.
- The one-issue-one-flag retry itself was built earlier and never run live; the owner declined that test before, so this one covers it.
