---
title: Flag Lifecycle: the flag is named after its issue and created at run start
type: task
status: resolved
assignee: ojones
blocked_by: [08-flag-lifecycle-domain.md]
---

## Question

Make flag naming and creation deterministic (STEP 4.1, 5.1, 5.2). (1) A `flag_slug(story_number)` in `flag_lifecycle/` returns `issue-<n>`, `<n>` the story's own number (a fix child, later, uses the failed story's number); the GrowthBook key stays `<app>.feature.issue-<n>`. (2) An idempotent `ensure_feature(gb, app, slug, issue_url, ...)` creates the GrowthBook feature with production OFF (description linking the story, `intake-<n>` tag, `flag_tags`) when it does not exist and never touches an existing one; the Build Run calls it in `setup` and writes the `flags.json` entry (slug and a description starting with the issue reference) before the coder starts, so the coder only wraps code. (3) `release_features.release_flags` stops creating: it only switches an existing feature on, after the same four gates; the retried story's own flag exception stays. (4) The coder is told the slug instead of choosing it; the planner's prompt stops asking for one and `validate_plan` drops its unique-slug check (unique by construction), while `flag: true|false` and `internal_only` stay. Update INV-38 and INV-39 and add "a flag's slug is `issue-<n>` of its story". Unit tests per transition: ensure creates once, ensure never touches an existing feature, release only switches on, a missing feature at release is an error.

## Added context

Source plan: "Changes 10". Works on today's story issues (the story number is the Update App Intake's number), so it does not wait for the planner move; if the Planning contract ticket (09) has landed, change the planner there instead of twice. Existing flags keep their old slugs; only new flags are named `issue-<n>`. Check `STANDARDS-FEATURE-FLAGS.md` (the Target lifecycle block becomes Built).

## Resolution (2026-10-19)

`ruff check` clean, 583 tests OK (3 skipped), `boundary_test` and `flow_spec_test` pass. Not committed. **Not yet run live**: the first update after the push is the proof (GrowthBook feature created off, `flags.json` commit, release switching it on).

**What changed.**
- **The plan only says "flagged".** `planner.validate_plan` accepts `flag: true` (no slug to check, no "shared flag" or "retry must reuse" rule); an older plan's own slug still validates. The planner prompt asks for `"flag": true`. `render_change_set_task` writes `flag_lifecycle.flag_slug.SLOT` (`{{flag_slug}}`) where the slug goes, so a child issue filed now has no number to bake in.
- **`flag_lifecycle/flag_slug.py`:** `for_story(n)` is `issue-<n>`; `name_in` fills the placeholder; `ensure_feature(gb, app, slug, issue_url, title, issue_number)` creates the GrowthBook feature with production OFF, the story link and the `intake-<n>` tag (still created without them if GrowthBook refuses), returns whether it created it, never touches an existing one, and stops the run (`NeedsHuman`) if GrowthBook cannot create it; `add_to_manifest` writes the `flags.json` entry with the issue reference first, once.
- **Build Run.** `BuildRun.name_the_flag`, called in `run()` right after planning and before the coder: fills the slug in the task and spec (a retried story keeps the flag it had, from its retry state), records `flags` in the Report, creates the feature, and makes a local orchestrator commit that records the flag in `flags.json`. A run whose task has no placeholder (a first build, an internal change, an older plan) is untouched.
- **Release never creates a flag** (the owner's decision, after the first version kept a creating fallback). `release_features.check_flags` looks at each declared flag without changing anything and `switch_on` switches on only the story's own flag (the one the run named, or the one a retried story keeps) when it exists and is off; every other existing flag is left alone (INV-06). This also fixes a bug found on the way: a manual re-run of a story whose first run left the flag created-off would never have switched it on. A flag that does not exist at release is handled by `flag_lifecycle/missing_flag.py` (INV-52):
  - **the code reads it** (dark, nothing can switch it on): the run ends `flag_missing`, a failure with no rollback and a message saying a flag that can be turned on has to be added in the next round, with a guess why; the story is labelled dark-broken and retried, and the retry's `ensure_feature` creates the flag.
  - **no code reads it** (live with no gate): clean tests leave it alone, the run ends `nothing_to_release` with a note; a failing test rolls the deploy back as a `regression` (the existing CI rollback), with the note.
  - Either way the run records `flag_notes` (slug, kind, a guess why) in the Report; the retrospective facts carry them and `lessons_from` files one `flag_missing` lesson, and a `flag_missing` fix request asks for the flag the task names.
- **Coder prompt:** use exactly the slug the task gives; do not add or edit the `flags.json` entry; never add a flag of your own; on a first build add no flag (the Factory creates flags only for updates). `STANDARDS-FEATURE-FLAGS.md` now says so.
- **Invariants.** INV-06, INV-38 and INV-39 reworded; new INV-51 and INV-52 "a flag's name is `issue-<n>` of its story and it exists, off, before the coder starts" with a test; the "rows that change" table lost INV-38 and the slug part of its "New" row.
- **Tests.** `flag_slug_test.py` (naming, ensure creates once and never touches an existing feature, extras refused, GrowthBook down, manifest entry once, garbage manifest); two new `release_features` cases; `NamingTheFlag` in `build_run_test.py` (named after the issue, created off, recorded and committed before the coder; the spec names it too; a retry keeps its flag and creates and commits nothing; no placeholder changes nothing); the plan renderer, the plan comment and `validate_plan` with `flag: true`.

**Left for later.** A fix child inheriting the failed story's number is the Try Fix ticket (15). The planner's other flag rules stay until the Planning contract ticket (09), which can now drop the slug-choosing text entirely.
