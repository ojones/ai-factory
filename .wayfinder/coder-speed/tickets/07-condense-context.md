---
title: Condense context on long runs
type: grilling
status: closed
assignee: ojones
blocked_by: [01-measure-where-time-goes]
---

## Question

Does context growth measurably slow runs against the 100k context_goal_tokens? If so, adopt a condenser (OpenHands-style) or trim tool output, and where?

## Resolution

No condenser built. Context is already measured per invocation (peak prompt tokens, condenser calls, cached tokens) and shown in the Build Run summary against `context_goal_tokens: 100000`, but no real coder state is on hand, so there is no evidence that context growth slows runs.

- **Done now:** one line in `agents/prompts/coder.md` to keep tool output small (line ranges, `tail -n 40` on long logs). It cuts context and time at no cost.
- **Trigger for more:** when a real Build Run summary shows a coder stage peaking over the 100k goal, or time per LLM call climbing across a long run, open a ticket to configure OpenHands' condenser for the coder or trim tool output further. Not before.
