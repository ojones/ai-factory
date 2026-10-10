---
title: Make reviewer/tester findings concrete
type: grilling
status: closed
assignee: ojones
blocked_by: []
---

## Question

What fields must a finding carry (file, line, failing command, suggested fix) so the coder can fix it without exploring? Change the findings schema and the reviewer/tester prompts accordingly.

## Resolution

- Findings may carry `file`, `line`, `requirement`, `suggested_fix` and `repro` (tester results carry `repro`). All best-effort, empty when not applicable; nothing is enforced. Added to the fast reviewer's JSON schema, the three prompts, and `agents/README.md`.
- The Orchestrator passes whatever is present through to the coder, and the fix list in the coder's task text now shows each blocking item inline (where, evidence, requirement, suggested fix, repro), not just its summary.
- Blocking means blocking: the evidence downgrade from "Cut review rounds" is reverted. The coder treats every blocking item as real and, if it truly cannot resolve one, says so plainly instead of working around it.
- If the rounds run out with something still blocking, the existing needs-human outcome is the alert; the log and learning loop for that is [Stuck runs alert the user and feed learning](11-stuck-run-handling-and-learning.md).
