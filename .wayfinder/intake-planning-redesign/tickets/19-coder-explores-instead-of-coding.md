---
title: The coder explored for 44 minutes and wrote nothing
type: research
status: open
assignee:
blocked_by: []
---

## Question

In the live proof (ai-factory#147, run 39441002463) the coder ran 44 minutes and 173 steps and never edited a file before the run stopped: it read `app.ts`, `routes/` and the bench-app spec, and tried to `curl` the parent issue #140 for context. The first Build Run of the same app (#146) took about 20 minutes and released. Find out why this one explored: was it the task (a DELETE route that collides with `/:id`), the model's speed (up to 140 s between steps), a loop, or the ticket text? The ticket text already pointed at the parent ("planned in #140"); that line is gone (ticket 18), so first re-run the same request and see whether it still happens. Then decide whether the Build Run needs a stall rule for "no edit after N minutes" (today only a silent Agent is killed, `agent_stall_minutes`) and whether `agent_timeout_minutes` (45) is the right ceiling for a coder that has produced no diff.

## Added context

Found in ticket 17. The run stopped for a different reason (the provider answered 402 at $0.13 of a $1.50 cap), so how far the coder would have gone is unknown. The coder was not writing code at the time of the 402; its last action was a `grep` and the `curl` of #140. Unit tests cannot find this: it needs a run and the Agent log (`openhands-coder-1.jsonl` in the run's artifact).
