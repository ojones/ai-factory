---
title: Tester speed
type: grilling
status: closed
assignee: ojones
blocked_by: []
---

## Question

After Deploy, a round takes as long as the tester, an exploring OpenHands agent on the 480B Qwen model (`agents/prompts/tester.md`). What would make it faster without missing real failures: a smaller or faster model (it only exercises HTTP endpoints), a scripted request plan the Orchestrator can run directly for each flag, a tight tool-call budget in the prompt like the reviewer's, or testing only what changed since the last passing round? The new per-invocation timing will show how long it takes today.

## Resolution

- **Prompt (`agents/prompts/tester.md`):** a budget of about 12 tool calls, no exploring beyond what each check needs, and requests for a flag batched into one shell script instead of one curl per turn.
- **Fix rounds:** the tester gets the previous round's report (`previous_report` placeholder, a path or "none"). It re-checks every prior failure in detail and re-runs previously passing checks as one batched script with no code reading, reading code only for new or changed flags. Decision: failed checks plus a fast full re-pass.
- **Orchestrator:** `previous_report` helper and the new placeholder; README table updated; tests pass.
- **Not done:** a smaller tester model (the tester only drives HTTP) and a scripted request plan. The model question rides on the [Coder smoke screen](14-coder-smoke-screen.md): add the tester to it. The scripted plan stays unspecified until we see tester timing.
