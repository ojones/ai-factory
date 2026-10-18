---
title: Rerun the reviewer and tester smoke fixtures and the replay under the new output shape
type: task
status: open
assignee:
blocked_by: []
---

## Question

The reviewer's output gained `category`, `evidence_kind` and `improvements`, its blocking decision now comes from banding, and the tester's report gained `scope` and `improvements`. The reviewer smoke test now sends the real schema and applies the real banding, but it has not been run with a model since, and neither has the tester smoke or the reviewer replay (`agents/replay`). Run them (a few cents each) and record whether the seeded bugs are still found, the clean diff still passes and the structured output is accepted by the model; fix the prompt or the fixtures if not.

## Added context

- Workflows: `smoke-reviewer-model.yml`, `reviewer-replay.yml`; the tester harness is `agents/smoke-tester/run.py`. This machine has no DeepInfra key, so run them on GitHub.
- A blocking finding with no cited line or repro is now minor, so a fixture that expected it to block may need its expectation or the prompt adjusted.
- Do this before the calibration ticket relies on the fixtures.
