---
title: Fast reviewer evidence and when to use it
type: grilling
status: closed
assignee: ojones
blocked_by: []
---

## Question

The decision so far is that a blocking finding blocks whatever detail it carries (no downgrade, no re-ask). Is that right for the fast single-call reviewer? How often does it leave `evidence` or the new detail fields blank on the smoke and replay fixtures, and does that predict wrong blockers? And when should the fast reviewer be used versus the exploring one: by diff size, build kind (first build vs update), or round?

## Resolution

No change needed. I ran the production fast reviewer over the 7 recorded cases: 7 blocking findings, **0 with blank evidence and all 7 with a file and line**. The strict JSON schema requires the fields, and the model fills them. So "blocking always blocks" (no downgrade, no re-ask) loses nothing on this evidence. (One recorded case, notes-v2-r3, was blocking when recorded and is clean now, because the flag policy since changed so a first build needs no flags.)

When to use which reviewer: the fast single-call reviewer is the default for every round and build kind; the exploring reviewer is only the fallback, already automatic when the diff exceeds `review_context_max_chars` (200,000) or the call fails. No size or round rule beyond that. Revisit if a real run shows the fast reviewer returning blank evidence or missing a real bug that the exploring one would find; the smoke fixtures in `agents/smoke` are the check to rerun.
