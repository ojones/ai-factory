---
title: App maintenance and security gates
type: grilling
status: resolved
assignee:
blocked_by: []
---

## Question

The Orchestrator builds and updates apps but does not keep them healthy afterwards: dependency and base-image CVEs, Node end-of-life, expiring tokens, and idle Fly apps that still cost money. What is the maintenance policy? Decide (a) cheap deterministic security checks in the Starter Template's Test Gate (`npm audit`, secret scanning, and whether CodeQL on public repos is worth adding), (b) scheduled maintenance Intakes (cadence, one per app or batched, flagged or not, given that bug fixes and dependency bumps are currently unflagged), and (c) a retire-or-keep policy for idle apps, and how it relates to the `teardown-managed-app` skill.

## Added context

- The Test Gate today is unit tests plus a boot smoke (STANDARDS-CODING.md); base image digests are pinned (STANDARDS-DEPLOYMENT.md), which stops silent updates and also stops silent patches.
- Template improvements do not reach already-seeded apps (pre-mortem row on template drift), so maintenance Intakes and template-sync Intakes may be one mechanism.
- Constraint: free and open-source tooling first (STANDARDS-CODING.md, Dependencies).
- Test bed: `ojones-todo` is a live, idle app: run `npm audit` against it, use it as the guinea pig for a scheduled maintenance Intake, and for deciding what 'idle' means before retiring an app.

## Resolution

(a) `npm run audit` (high or critical, production dependencies) in the Starter's Test Gate; GitHub already scans public repos for secrets, so nothing added for secrets; CodeQL not added. (b) Dependabot detects daily (npm, Docker, Actions); a daily Orchestrator pass turns the npm and Docker pull requests into one self-starting Update Intake per app (INV-35); the Starter's base image moved from an ARG on end-of-life Node 20 to Node 22 written in the FROM lines. (c) Idle apps are reported (days since last push) in the Fly audit summary and never retired automatically; teardown stays a manual workflow. Template sync delivers `dependabot.yml` and `test-gate.yml` to existing apps.
