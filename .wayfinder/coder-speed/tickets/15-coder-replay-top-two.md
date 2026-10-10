---
title: Coder replay for the top two
type: task
status: open
assignee:
blocked_by: [14-coder-smoke-screen]
---

## Question

Extend the replay (`agents/replay`) to run the coder: check out a recorded app at its base commit, run the coder with a candidate model on the original task, and score with build, tests and the reviewer, with repeats because the model is not deterministic. Run the two finalists against the 480B Qwen. Does either have equal pass rate and at least 30% less time? If so, set it as `model` and the 480B as `fix_model` in `agents/profiles.yml`.
