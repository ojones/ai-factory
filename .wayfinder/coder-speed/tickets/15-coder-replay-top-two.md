---
title: Coder replay for the top two
type: task
status: closed
assignee: ojones
blocked_by: [14-coder-smoke-screen]
---

## Question

Extend the replay (`agents/replay`) to run the coder: check out a recorded app at its base commit, run the coder with a candidate model on the original task, and score with build, tests and the reviewer, with repeats because the model is not deterministic. Only one finalist survived the smoke screen, so run DeepSeek-V4.1-Flash against the 480B Qwen (a second candidate only if one appears). Does either have equal pass rate and at least 30% less time? If so, set it as `model` and the 480B as `fix_model` in `agents/profiles.yml`.

## Resolution: coder replay run (6 runs per model, 3 on each of the two recorded real tasks)

Built `agents/replay/coder_replay.py`: checks out each recorded app at its base commit (history kept as bundles), runs the real round-1 coder prompt with the INTAKE.md Spec as the task, then scores it with the repo's own `npm run build` and `npm test`, plus the production single-call reviewer on the resulting diff. `ok` = built and no blocking finding, i.e. no second round needed.

| Model | ok (built + clean) | Built | Median wall | Avg cost/run | Avg calls | Avg blocking findings |
|---|---|---|---|---|---|---|
| Qwen3-Coder-480B (baseline) | **0/6** | 6/6 | 202 s | $0.19 | 36 | 2.3 |
| DeepSeek-V4.1-Flash | **6/6** | 6/6 | 165 s | $0.03 | 25 | 0 |

- **Quality, not just speed, separates them.** Every baseline run built and passed its own tests yet had 1-3 real blocking problems: `const { text } = req.body` throws a 500 on a missing body, and the delete button rendered with no flag. DeepSeek avoided both in all 6 runs. Each baseline run would have needed at least one more round, each costing a push, CI and deploy wait, review and test.
- **Not a self-preference artifact:** the reviewer is also a DeepSeek model, so I read the actual code. DeepSeek guards the body (`(req.body as ... | undefined)?.text`), mounts after the kill switch, and gates the button through a backend flag endpoint; the baseline has the bug the reviewer named. Checked on 4 of 12 outputs, not all.
- **Per round DeepSeek is 18% faster, 6x cheaper, and it removes most extra rounds.** One DeepSeek outlier ran 683 s and 58 calls (a long tail worth watching).
- **Only two distinct real tasks**, both the same kind of app; this is evidence, not proof. The smoke screen separately showed DeepSeek missing the todo task's distinct-id assertion 3 of 3 times.
- A first attempt wasted about $2 because the reviewer prompt path was wrong; fixed, and working directories are now kept (`KEEP=1`).

Decision: `agents/profiles.yml` now sets the coder `model` to DeepSeek-V4.1-Flash for all rounds; `fix_model` stays unset (the 480B is not shown stronger, and an escalation model would need its own test). Revisit if real runs show it stuck in fix rounds.
