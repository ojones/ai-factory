---
title: File the bug Intake and close the loop
type: task
status: resolved
assignee: ojones
blocked_by: [15c-try-fix-agent-and-bug-template.md]
---

## Question

Build steps 7.1, 7.2, 7.4 and the bounds. `try_fix/file_bug.py`: for a `fix` verdict, (a) on a dark story add the failure as an idempotent comment on the existing story (marker `<!-- bug:{key} -->`) and file a bug Intake (`update-app-intake`, `bug`, `app:<app>`, filed with the PAT through `request/file_intake`, label via `ensure_label`) carrying hidden `fix_for` and `flag_story`; (b) after a release that is still on, file a bug Intake with no marker and a fresh flag and comment the link on the story; (c) a Factory target files the same template in ai-factory (`fix-request`, with the existing learning PR and `failed-child` resume path); dedupe by event key. Planning: `plan_run`, `file_children` and `render_child` read `fix_for`, copy `flag_story` onto the single fix child, block the failed child on it and give it `waiting-on-plan`; the plan gate rejects a `fix_for` plan with more than one child. `retrospective/close_child.py`: when a bug Intake closes with `fix_for`, advance the origin parent and post the solution comment on the story. Attempt bound: count along the `fix_for` chain back to the original story (rework `fix_child.attempts_used`), `fix_attempts_max` then `needs_human.hold`. Retire `fix_child.file_fix_child` and its in-plan fix children (move first, then change); `route.py` takes the target from the verdict. Update invariants INV-26, INV-27, INV-31 (partly, see 16), INV-39 and their tests. Unit tests with `FakeIssues`: dark path, released path, factory path, dedupe, one-child gate, chain bound, close advances origin and comments, an unchanged child is never restarted.

## Added context

Flow spec "From a failure to a fix" rules 4 to 7. Dark = never released, off, or switched off by the watchdog (the fix keeps STEP 5.5's same flag); released = released and still on.

## Resolution

Built. A `fix` verdict now becomes a bug ticket written by the Try Fix Agent and filed as an Intake; the fix-child filing of ticket 15 is gone.

- **Filing** (`try_fix/file_bug.py`, dispatched by `try_fix/file_failure.py`, called from `run_retrospective.py` for every `fix` verdict, warnings included): one bug per event key (the key is in the title; a repeat comments "Seen again"). The target is the verdict's, else the cause's (`route.py`: Factory cause, none or infrastructure, otherwise the app). **Dark story** (the event's story is an open planned child and its flag is not released, which includes a watchdog switch-off): the failure is commented once on the story, the bug Intake carries a `fix-for` marker (`fix_for`, `flag_story`, `origin_parent`, `flag`, `attempt`, in `shared/child_tickets.py`) and the failed child's own instructions, the failed child is blocked by the Intake and gets `waiting-on-plan`, and `update-app-intake` is added last with the PAT so planning starts only after the block exists. A refusal to block takes the Intake back and holds the child. **Released** (flag still on) or no story or not a planned child: a plain bug Intake, fresh flag, the story is told its number. **Factory or none**: one `fix-request` issue in ai-factory from the same template with the `failed-child` marker; an open failed child is held `needs-human` (the learning PR and `resume-failed-child.yml` are as before).
- **Planning** (`planning/fix_for.py`, `plan_run.py`, `file_children.py`): the planner is told to plan exactly one change set; the plan gate refuses more (`needs_human`, the Intake can be re-labelled); the one child gets `flag_story`, `fix_for` and `fix_attempt` in its marker and the failed child's flag setting, so the Build Run names the flag `issue-<failed story>` and `fix_note.py` (moved from `fix_child.py`) tells the reviewer and tester.
- **Closing the loop** (`retrospective/close_child.py`): when a plan closes with its last child and its body has a `fix-for` marker, `settle_fix` comments on the story that the fix is done and advances the plan the failed child belongs to, which starts that child (not its siblings), because it was blocked by the Intake.
- **Bound**: the attempt number is carried along the chain (a fix child that fails files a bug whose `fix_for` is that fix child, attempt + 1, same `flag_story`); after `fix_attempts_max` (2) the failed child is held `needs-human` and nothing is filed. A mid-chain fix child that finishes later restarts the child above it, so the original child resumes last.
- Removed: `fix_child.file_fix_child`, `fix_task`, the in-plan fix children and `attempts_used`; the approach guidance moved into the Try Fix fallback text. INV-26, INV-27 and INV-39 now describe this and their tests exercise it with `FakeIssues` (`FakeIssues` gained `issue create/list/comment`). New tests: `file_bug`, `file_failure`, `fix_note`, the planning gate and marker, `settle_fix`.

Known limits: if the planner still splits a fix into several change sets the Intake stops `needs_human` with the failed child still blocked (a person re-labels it); nothing has run live, so the cross-parent blocker, the label-last planning start and the `settle_fix` advance are untested against real GitHub. Warnings that get a `fix` verdict are filed even when their story is closed (a plain bug Intake).
