---
title: Cut review rounds
type: grilling
status: closed
assignee: ojones
blocked_by: []
---

## Question

review_rounds is 10 and each round is a full coder run plus review and test. Do we lower the cap, limit blocking findings per round, or restrict later rounds to blocking items only? What first-pass quality checks belong in the coder prompt?

## Resolution

- **Cap is 4** (`review_rounds` in `agents/profiles.yml`): round 1 plus three fix rounds.
- **Evidence rule reversed later.** An evidenceless-blocker downgrade was added here, then removed in "Make findings concrete": blocking means blocking.
- **Fix rounds are narrow** (`agents/prompts/coder.md`): round 2+ fixes blocking items only, ignores minor items, and runs just the build and affected tests; CI and the tester run the rest.
- **Not done here, spun out as tickets:** what happens when a run hits the cap (alert plus learning), and what happens to minor findings (GitHub issues, picked up later, feeding template fixes).
