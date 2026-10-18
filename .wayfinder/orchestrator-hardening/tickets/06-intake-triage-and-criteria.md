---
title: Intake triage, criteria echo and golden Intakes
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

Agents verify against whatever the Intake says, so spec quality is the biggest lever and the Intake is still one free-text field. Decide (a) a feasibility triage before any money is spent: is the request inside the pinned Express + React stack and the free-dependency rule, or does it need payments, third-party secrets, personal data or an external API, and what happens then (refuse, escalate, proceed with a flag), (b) an owner-confirmed criteria echo: the Orchestrator derives numbered acceptance criteria and posts them for confirmation, and for which Intakes (all, or only larger or costlier ones), and (c) a small set of golden Intakes that show the expected shape.

## Added context

- Managed App repos are public (ARCHITECTURE.md, Deployment provisioning), so `INTAKE.md` and the code are public; the triage should warn about secrets and personal data in the spec.
- `parse_intake` and the Intake Issue Form fix the current fields; the cost-cap override is the only structured one.
- The reviewer and tester currently treat `INTAKE.md` as the spec for every build, including later updates; this ticket should settle where an update's task and criteria live.
- Only owner-authored Intake text and comments should reach Agents.
- Test bed: file Update Intakes for `ojones-todo` that the Factory should refuse or question (payments, API keys, personal data) and see what the planner does. Evidence so far: for a self-contradicting request it chose a reading itself and recorded it as an assumption instead of asking (Update Intake #58, soft delete).

## Resolution (2026-10-13)

(a) Feasibility triage: the planner marks a request `blocked` (payments, secrets, personal data, an outside keyed service, outside the stack) and the run ends `refused` right after the planner call; a deterministic secret scan refuses an Intake containing a real secret value before any spend (INV-40). A refusal is answered on the Intake issue with reasons and what could be built instead; it is not reverted, retried, filed as a failure or learned from. Chosen with the owner's standing preference (no human in the loop): refuse, do not ask. (b) Criteria echo: the planner's numbered criteria are posted on the issue as before, with no confirmation step (post and go). (c) `docs/golden-intakes.md` shows good and refused requests, linked from the Update Intake form. Not done: a first build still has no planner, so only the secret scan applies to it; the planner-judged refusal for first builds would need a planner run in App Staging.
