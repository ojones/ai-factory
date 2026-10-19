# Feature-Flag Standards

Part of [STANDARDS.md](STANDARDS.md). See [GLOSSARY.md](GLOSSARY.md) for terminology. GrowthBook hosting and per-Managed-App provisioning lives in [ARCHITECTURE.md](ARCHITECTURE.md#feature-flag-infrastructure) — this file covers only what a Managed App's own code must do.

## Flagging policy

A flag protects `main`. All work lands directly on a single `main` with no branches ([STANDARDS-CODING.md](STANDARDS-CODING.md#git-workflow)), so a flag is what keeps a change that is not yet proven from reaching users. The policy follows from that:

- **A Managed App's first build needs no flags.** There is nothing yet to break, and the mandatory kill switch below still covers the whole app. The first build goes live on deploy. A flag there is allowed, and an Intake that asks for one gets it, but the coder is not required to add one and the reviewer never treats a missing flag as a finding.
- **Every later update to an existing app that changes behaviour a user can see or reach is protected by a flag.** Changes with no user-visible effect (internal refactors, dependency bumps, a bug fix that only restores documented behaviour without altering what a user can reach) may ship unflagged; see [Release and retirement](#release-and-retirement). If in doubt, flag it: a flag is cheap and the rollback lever is the point. An update ships dark behind a flag of its own, and is released only after review and tests pass. Each update gets its own flag, separate from earlier updates', so one can be turned off without touching the others.
- **A flag covers the change, not each route or screen.** One flag around everything the change encompasses is enough. Neither the coder nor the reviewer needs a flag per endpoint or UI piece, though finer flags are allowed where they help.
- **What the Intake asks for stands.** If it names a flag, the flag is a requirement like any other.

This is the production safety net, and also the review gate, compensating for the direct-push-to-main, no-branch git workflow.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md)

## Mandatory kill switch

Every Managed App ships, baked into the Starter Template, one global kill-switch flag, checked once in top-level middleware, returning a maintenance response when off — identical in *shape and placement* across every Managed App, but not a literal identical key (see Code wiring): all Managed Apps share one GrowthBook project, so an app-scoped key is what keeps one app's kill switch from flipping another app's.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [#22](https://github.com/ojones/ai-factory/issues/22)

## Code wiring

All Managed Apps share one GrowthBook project (see [ARCHITECTURE.md](ARCHITECTURE.md#feature-flag-infrastructure) — the free self-hosted tier caps at 1 project), with no GrowthBook-level boundary between apps. The flag-key naming convention carries the only isolation that exists, and so is app-scoped: **`<app-slug>.feature.<slug>`** for per-feature flags, **`<app-slug>.global-kill-switch`** for the mandatory kill switch. The app slug is derived live by the Managed App's own code (e.g. from its repo name, the same env/derivation already used for the Fly app name per [#21](https://github.com/ojones/ai-factory/issues/21)) — never injected or persisted by App Staging, keeping the Starter Template's flag-handling code unmodified per app.

A single OpenFeature client is initialized once at app startup from the SDK connection key env var — not re-derived per feature. The client polls for live flag updates (`pollingInterval`) rather than using SSE streaming, which GrowthBook's own docs confirm is cloud/proxy-only, not available to a bare self-hosted instance.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [build ticket #14](https://github.com/ojones/ai-factory/issues/14), [#22](https://github.com/ojones/ai-factory/issues/22)

## Resilience

Every OpenFeature call site must supply a real, sensible default value. Resilience against a GrowthBook outage comes from OpenFeature's own spec guarantee (flag evaluation always returns the default value on abnormal execution, never throws) — not from any GrowthBook-specific caching behavior.

**That default must always be `false` for a boolean flag — never `true`.** Confirmed live against `@openfeature/growthbook-provider@0.1.2`: GrowthBook represents an "off" boolean as `value: null`, and this provider's `translateResult` unconditionally substitutes the caller's default for any `null` value, with no way to distinguish "off" from "not found." Passing `true` makes a flag's off state permanently unobservable — the flag could never actually turn anything off, defeating its entire purpose. The real tradeoff this forces: "intentionally off" and "GrowthBook unreachable" become indistinguishable, so every flag fails *closed* on an outage, not open, for as long as this library bug stands. Revisit this note if a future `@openfeature/growthbook-provider` release fixes it.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [build ticket #14](https://github.com/ojones/ai-factory/issues/14)

## Flag manifest

Every new flag is recorded in `flags.json` at the repo root — an array of `{slug, description}` entries — in the same commit that introduces it in code. (The slug is the `<slug>` part of the key; the release step prefixes the app slug. No added-in commit is recorded: a commit can't contain its own hash.) The release step reads the manifest to know what a Build Run introduced. A flag need not exist in GrowthBook for code to ship dark: a missing flag evaluates to `false`, so the release step creates it in GrowthBook at release time.
→ [issue #24](https://github.com/ojones/ai-factory/issues/24)

## Preview

Every Managed App's flag wrapper honors a **Preview Token** so the tester can exercise a dark feature in the real deployment. A request carrying the token — as an `X-Preview-Token` header, or a `?preview=<token>` query parameter that sets an HttpOnly cookie for browser sessions — evaluates every `feature.*` flag as on. The token is compared against the `PREVIEW_TOKEN` env var. The override never applies to the global kill switch, and it works when GrowthBook is unreachable. Without a valid token the feature stays dark to everyone.
→ [issue #24](https://github.com/ojones/ai-factory/issues/24)

## Release and retirement

**Release** is the flag being enabled for all users. It is performed by a deterministic Orchestrator step after review and tests are clean, never by an Agent, and leaves every flag that already exists in GrowthBook exactly as it is, with one exception: a retried story's own flag (see below) that the watchdog switched off is switched on again once the fix passes the gates.

**A flag has one job**: to stage a change dark and release it when it is safe. It belongs to the release pipeline end to end; nobody flips it by hand for any other purpose, and the Orchestrator may rely on that. It is short-lived by design.

**Retirement** — deleting a flag's check and its line in `flags.json`, keeping the behaviour on — is automatic, under the owner's standing approval recorded here, and it never costs a run of its own: it rides along in an Update App Intake's Build Run that is already coming in for the same app. At the start of that run the Orchestrator picks every flag (up to `limits.flag_retirement.piggyback_max`, 5, oldest first, so a backlog clears) that was released, was never switched off by the watchdog, is still in the manifest, was released on an earlier day, and has a **later Build Run that also ended `released`** after it (a run that ended `nothing_to_release` does not count). The coder removes each flag's check in a separate commit, the tester checks the behaviour is still on for an ordinary visitor, the Orchestrator rejects the commit while code (not a comment) still mentions a retiring slug, and when the run ends well the retired flags are archived in GrowthBook. The newest release therefore always keeps its flag. A first build and an automatic retry retire nothing. Agents still never decide to retire a flag themselves. A flag the watchdog switched off is not retired: its story is retried with the same flag (below).

**Story and flag.** One issue (the story) and one flag stay together for the whole life of a change. When an update's flag is released, the Orchestrator labels the issue `flag:<slug>`, adds `[flag: <slug>]` to its title and comments the full key; the GrowthBook feature carries the issue link in its description and an `intake-<n>` tag; the flag's entry in `flags.json` starts its description with the issue reference; the App State issue links each flag to its story; and when the flag is retired the story gets a comment saying so.

**A failure keeps its story and its flag.** When a release breaks and the watchdog switches the flag off, nothing new is filed. The story's own issue gets a comment saying it broke, and is retried automatically (at most `fix_request_max_attempts`, 2): the fix is made behind the same flag, goes through the same gates, and the release step switches that same flag on again when it passes. If it cannot be fixed within the retries, the issue stays open, labelled `needs-human` and `dark-broken`, attached to its flag (a `flag:<slug>` label), which stays off. Its code stays in `main`, dark. That is a **dark feature**: it is tracked by its story issue and the flag, not by `flags.json`, and it is removed only when a person adds `approve-retire` to the story, which files an Update App Intake that deletes the flag, its code and its tests.

**Target lifecycle (flow spec group 5, STEP 4.1 to 5.7; not built yet).** The paragraphs above describe what runs today; the redesign keeps the lifecycle (one story, one flag; short-lived; retired by riding along in a later run; a dark-broken feature removed only after `approve-retire`) and makes its mechanics deterministic and named after the issue:
- **Name.** The slug is `issue-<n>`, `<n>` the number of the story's child ticket; a fix child uses the failed story's number, so a failure keeps its flag by construction. The planner no longer chooses a slug; it only says whether the change set is flagged or internal only. The GrowthBook key stays `<app-slug>.feature.issue-<n>`.
- **Created at the start of the child's Build Run.** The Orchestrator creates the GrowthBook feature (production off, description linking the story issue, tag `intake-<n>`) and writes the `flags.json` entry before the coder starts, so the coder only wraps code and the flag exists while the coder and tester work. Release only switches production on, after the same four gates. Existing flags are never touched; a story's later children reuse its own.
- **Dark mode is unit tested.** The Starter provides a test helper `withFlag(slug, on, fn)`, and `npm run check` fails a commit when a slug in `flags.json` lacks a flag-off test or a flag-on test, or has more than one entry point.
- **Retirement removes the tests too.** The coder deletes the flag check, the `flags.json` line and the flag-off tests, and unwraps the flag-on tests, in its own commit; the Orchestrator rejects the commit while the slug still appears in code, tests or `flags.json` (comments aside). Only the owner-approved `approve-retire` is planned, as one child with no flag.
- **A failure keeps its flag through a fix child** (STEP 7.1) instead of an automatic retry of the unchanged issue.
- **Bugs after release.** While the flag is dark or off the work is not finished and the same story stays open; once the flag is on and validated a bug is a regression, filed as a new `update-app-intake` labelled `bug` and planned like any change (STEP 8.4).

**Built to be removed.** One change set has one flag, checked at the single entry point of the change with a plain string literal, so retiring it is deleting that one check. The reviewer flags a flag scattered across unrelated places.

Unflagged changes (bug fixes, refactors, dependency bumps, retiring a flag) go live on deploy, so the reviewer checks them before they are pushed and the Test Gate and the tester check them after. They are fixed forward if they fail; nothing is ever reverted in git, and the only thing taken back is the live deployment, rolled back through CI to the previous version, and only for a regression the tester observed (see ARCHITECTURE.md: Nothing is reverted in git). On an update, a user-facing change with no flag around it is a blocking finding; on a first build it is not.
→ [issue #24](https://github.com/ojones/ai-factory/issues/24)
