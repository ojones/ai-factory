---
title: Split big tasks
type: grilling
status: closed
assignee: ojones
blocked_by: [01-measure-where-time-goes]
---

## Question

Would splitting large tasks into smaller independent pieces (separate worktrees) beat one slow run? Evidence from the ChatGPT notes says it paid off only on long-horizon work; is it worth it for Managed App builds?

## Resolution

Not now. Splitting a task into independent pieces on separate worktrees pays only when a single coder run is long, and it adds a merge step and a decomposition step that can themselves fail. With the changes in this map the coder runs 140-250 s typically on real tasks (one 683 s outlier of 12), and the first-round bugs that cost extra rounds are fixed at the source rather than by parallelism. The earlier ChatGPT notes also said parallel agents paid off only on long-horizon work.

Trigger to reopen: a real Build Run summary shows a coder stage over about 15 minutes, or a peak context over the 100k goal, on a task whose pieces are genuinely independent. Until then, no build.
