---
title: Calibrate the review-finding rules and lint rules from real runs
type: research
status: open
assignee:
blocked_by: [19-payoff-metric-and-review-findings-measure]
---

## Question

The finding band rules (a blocking label blocks only with a blocking category and a cited line or repro), the retest rule for blocked checks and the first lint rules were set from reasoning and a few examples, not measured. Once there is history, score the past findings under the rules: how many runs would have released earlier, what would have escaped, how many rounds went to findings the rules now treat as minor, and how often a lint rule fires on real code. Adjust the categories, the evidence requirement and the thresholds from that, and from the reviewer seeded-bug fixtures (`agents/smoke`).

## Added context

- Blocked by the metric ticket: there is not enough history yet.
- Run the reviewer smoke fixtures under the new schema first (ticket 23); they measure recall of the seeded bugs and the false-positive rate on the clean diff under the banding.
- Relates to tickets 14 (resolved, thresholds parked) and 15 (resolved, first lint slice).
