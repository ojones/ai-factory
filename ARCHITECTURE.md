# Orchestrator Architecture

Decisions about how the Orchestrator itself is built and operated — for whoever implements the v1 Orchestrator. Distinct from [STANDARDS.md](STANDARDS.md): nothing here is something a Managed App's own code needs to follow. Terminology follows [GLOSSARY.md](GLOSSARY.md).

Each decision links back to its ticket in `.scratch/orchestrator-spec/issues/` for the full comparison, runner-ups, and citations.

## Agent runtime

The Orchestrator reuses an existing open-source CLI coding-agent harness rather than a custom LLM loop — shrinks build scope and matches the Factory's open-source lean.

**Harness: [OpenHands](https://github.com/All-Hands-AI/OpenHands)** (MIT). SWE-bench-leading, pluggable to open-weight models via LiteLLM, purpose-built `--headless` CLI mode with `--json` structured output. Runner-up: mini-swe-agent.
→ [issues/01](.scratch/orchestrator-spec/issues/01-agent-runtime-reuse-harness.md), [issues/07](.scratch/orchestrator-spec/issues/07-which-agent-harness.md)

## Agents and Build Run stages

A Build Run runs several Agents in sequence, each a separate headless OpenHands invocation with its own role prompt. Role prompts live in ai-factory, not in the Managed App repo, so the coder can't edit its reviewer's instructions. Agents hand off through `main` and structured JSON files (findings, verdicts), never through branches or PRs. **The coder is the only Agent whose work reaches `main`**, but it only commits: the Orchestrator holds the PAT and does the push, so no Agent can read a credential from its checkout or environment. The Orchestrator rejects and discards a coder commit that touches the Starter Template's protected files (`.github/`, `fly.toml`, `fly/`, the flag wrapper `feature-flags.ts`, `INTAKE.md`), since the workflows hold the Fly token.

**Roles**
- **Coder**: implements the task from the Intake issue, committing to `main` for the Orchestrator to push. Every user-facing change goes behind a feature flag recorded in `flags.json` ([STANDARDS-FEATURE-FLAGS.md](STANDARDS-FEATURE-FLAGS.md)). Runs on the pinned Qwen3-Coder model.
- **Reviewer**: read-only on code. Reviews the pushed code on `main` and emits a structured JSON verdict with findings. Missing flags on user-facing changes are its top-priority finding; it wraps nothing itself and sends the finding back to the coder. **The Orchestrator derives the verdict from the findings** (any blocking finding means changes requested) and ignores the model's own `verdict` field: in testing the model wrote "clean" on every diff, even while listing blocking findings. When the reviewer is asked for structured output, the schema must put analysis and findings before the verdict, because generation follows property order and a verdict-first schema approved every diff, including an obvious command injection. Its model should differ from the coder's, since a clean review releases to everyone and a shared model shares blind spots; the pick is a research ticket, not decided here.
- **Tester**: runs the deployed app and exercises the dark feature using the Preview Token. Can't push. Runs on the pinned model.
- **Pipeline Agent**: invoked only when CI or the deploy fails. Deterministic polling does the normal watching, so the happy path costs no tokens. It diagnoses from the failing run's logs and Fly status, which the Orchestrator gathers into files for it (it holds no GitHub or Fly credential), and hands a fix request back to the coder. It can't edit code or workflows.

**Stages, in one Build Run**
1. The coder pushes to `main`.
2. CI, the build, and the deploy run (the Test Gate and workflows are unchanged). The new feature is **deployed dark** because its flag is off. Failures go to the Pipeline Agent and back to the coder, bounded by the cost cap and time limit as before.
3. The reviewer and tester examine the deployed app. Findings go to the coder, who pushes fixes to `main`, still dark. This loop is a fixed, configurable number of rounds, default **10**; a round is one review and test pass followed by one fix commit.
4. **Release**: a deterministic Orchestrator step, never an Agent, creates and enables the new flags in GrowthBook, but only when all four hold for the pushed SHA: CI green, deploy healthy, the tester's preview run passed, and the reviewer's verdict clean. It then posts a "released" comment in the Managed App repo. Rolling back is the owner flipping the flag off in GrowthBook; the step never re-enables a flag that already exists.
5. If the round limit, cost cap, or time limit is hit first, the flag stays off, no release happens, and a "needs human" or "budget exhausted" Issue is opened in the Managed App repo. Dark-by-default makes this the safe outcome, so no budget is reserved for later stages. One deterministic final step always writes the Summary and Issue even after a breach.

**Credentials**: Agents run as subprocesses with a whitelisted environment: their own scoped DeepInfra JWT, plus the Preview Token for the tester. They get none of the PAT, Fly token, DeepInfra parent key or GrowthBook admin key. **Known gap:** Agents run as the same OS user as the Orchestrator, so a hostile Agent could read the Orchestrator's process environment from `/proc`; closing that means running Agents as a separate user. No Agent holds the GrowthBook admin key. The key's scope isn't app-scoped (all Managed Apps share one project), so an Agent holding it could change any app's flags or kill switch, and the release step is the gate the Agents are being checked against. Agents read flag state with the app's SDK key if they need to.

**Cost**: all Agents share the Build Run's one capped credential. The "refuse the next turn" rule applies run-wide; there are no per-Agent budgets.

**Retirement**: deleting a flag and its code path happens only on an explicit request from the owner, as a normal Intake. No Agent proposes or performs it unprompted.
→ [issue #24](https://github.com/ojones/ai-factory/issues/24)

## Model serving

Open-weight model inference is consumed via a pay-per-token API, not self-hosted GPU inference — Build Runs are bounded, not continuously GPU-saturated, so idle self-hosted cost would dominate.

**Provider/model: [DeepInfra](https://deepinfra.com) serving `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo`** (Apache 2.0). Cheapest confirmed per-token price for a model RL-trained for long multi-turn tool-calling agentic loops; leads open-weight models on agentic tool-use benchmarks. Runner-up: Together AI (same model).

**Reviewer model: `deepseek-ai/DeepSeek-V4-Pro-0813`** (MIT, 1M context, $1.30 in / $2.60 out per 1M tokens), a different lab than the coder so a clean review isn't a shared blind spot. Runner-up: `DeepSeek-V4.1-Flash`. Smoke-tested ([#33](https://github.com/ojones/ai-factory/issues/33), `agents/smoke/`): `usage.estimated_cost` is returned, tool calls and structured output work, it found all four seeded bugs (off-by-one, command injection, missing flag, flag default `true`) in 3 of 3 trials and passed a clean diff in 2 of 3 (one false positive), and it reviewed correctly end to end through OpenHands. A full 5-fixture, 3-trial pass costs about $0.02. No code-review benchmark covering open-weight models exists, so beyond this smoke test the quality case rests on owner-reported agentic-coding numbers.
→ [issue #25](https://github.com/ojones/ai-factory/issues/25), [research](https://github.com/ojones/ai-factory/blob/research/reviewer-model/.scratch/orchestrator-spec/research/reviewer-model.md)

**Models, prompts, and limits are config, not architecture.** Every per-role model, the provider endpoint, each role's prompt, and the review-round limit live in [agents/](agents/README.md), so any of them can be switched or tuned without editing this document.
→ [issues/02](.scratch/orchestrator-spec/issues/02-model-serving-api-not-selfhosted.md), [issues/08](.scratch/orchestrator-spec/issues/08-which-model-provider.md)

## Orchestrator host

The Orchestrator runs as ephemeral compute during a Build Run, not an always-on service — pay only while a Build Run is active.

**Platform: GitHub Actions** (GitHub-hosted runners). Native scheduling (`on.schedule`), secrets, and run logging with zero extra infrastructure; clears the 6-hour-per-job duration bar for an overnight run. Runner-up: Fly Machines.
→ [issues/03](.scratch/orchestrator-spec/issues/03-orchestrator-host-ephemeral.md), [issues/09](.scratch/orchestrator-spec/issues/09-which-compute-platform.md)

## Deploy target for Managed Apps

Deployment pins one default hosting target for v1 simplicity, but the mechanism must stay swappable per project — never hardcode an assumption the target is fixed forever.

**Default: [Fly.io](https://fly.io)**. Cheapest at low-traffic scale, lowest-friction GitHub Actions deploy flow. Runner-up: Railway.
→ [issues/04](.scratch/orchestrator-spec/issues/04-deploy-target-default-swappable.md), [issues/10](.scratch/orchestrator-spec/issues/10-which-deploy-target.md)

**IaC approach: `fly.toml`** (checked into each Managed App's repo) as the sole declarative app-config, paired with a thin, checked-in, idempotent provisioning script for what it can't express (secrets, DNS/certs, registry auth). Fly's own current recommendation — their official Terraform provider is archived and un-recommended by Fly.io itself.
→ [issues/15](.scratch/orchestrator-spec/issues/15-which-iac-approach.md)

## Cost guardrails

The spec requires a budget cap + hard stop exist and are enforced; concrete dollar figures are build-time config, not part of this spec.

**Enforcement mechanism**: the cap covers LLM token spend only (not GitHub Actions minutes or other metered calls). DeepInfra refuses a spending-limited JWT that carries more than one model (HTTP 422, "multiple models is not compatible with spending_limit", found building #32), so each Agent invocation gets its own **single-model scoped JWT** (DeepInfra `POST /v1/scoped-jwt`) whose `spending_limit` is what is left of the run's cap. All Agents therefore still share one cap, and the Orchestrator meters the run as the sum of every JWT's spend. Each JWT is both enforcer and meter. DeepInfra refuses the first call after the limit is crossed with HTTP 403, `token spending limit exceeded`, while the call that crosses it still completes, which is exactly "finish the current turn, refuse the next". The Orchestrator reads each JWT's spend from `GET /v1/scoped-jwt?jwtoken=<jwt>` (`spending_current`, USD) after its Agent invocation, for the Summary and Report and to skip remaining stages once the cap is reached. Verified empirically ([#35](https://github.com/ojones/ai-factory/issues/35)): `spending_current` equalled the sum of per-response `usage.estimated_cost` with no lag. This replaces summing `usage.estimated_cost` per response, which OpenHands' headless mode can't supply, and the earlier account-wide usage diff, which can't separate concurrent runs.

**Worst-case overshoot** is one call's cost, because the crossing call completes (normally fractions of a cent; a very large-context call to the reviewer model could be a few tenths of a dollar). The DeepInfra account-level spend cap remains the last-resort ceiling. Each JWT is masked in logs, lives in the single Build Run job, and expires after the configured lifetime (default 6 hours, the Actions job limit); a compromised dependency in an Agent's environment could spend at most the JWT's remaining budget on that role's model.

**Numbers are config** in `agents/profiles.yml` (`limits`): the default cap (**$2.00**), the ceiling an Intake override may request (**$10.00**, enforced at Intake), and the JWT lifetime. They are starting values to revise after the first real multi-agent run.
→ [issues/05](.scratch/orchestrator-spec/issues/05-cost-guardrails-mechanism-not-numbers.md), [issues/14](.scratch/orchestrator-spec/issues/14-cost-guardrail-design.md)

## Visibility

A minimum observability/reporting requirement for unattended Build Runs is part of the architecture.

**Mechanism**: a **Build Run Summary** written to `GITHUB_STEP_SUMMARY` (status, what changed, test results, cost spent, deploy outcome + a link to that deployment's Fly log viewer). The raw OpenHands `--json` JSONL event stream is uploaded as a build artifact for deep-dive debugging. A curated, machine-readable **Build Run Report** (same fields as the Summary) is produced alongside it for future tooling. The Summary has a row per stage (Agent, rounds used, cost, verdict) plus the release outcome, and each Agent invocation uploads its own JSONL artifact; the Report carries the same fields. On failure — a crash, the cost/time budget exhausted before CI went green, or the review-round limit reached without a clean verdict — an explicit workflow step auto-creates a GitHub Issue in the Managed App's repo, distinguishing which.
→ [issues/06](.scratch/orchestrator-spec/issues/06-visibility-in-scope.md), [issues/13](.scratch/orchestrator-spec/issues/13-visibility-standard-design.md)

## Intake

A Managed App's build begins with an **Intake** issue — a GitHub Issue Form on this repo (ai-factory) labelled `intake`, titled the Managed App's name (kebab-cased for the eventual repo name), carrying two fields: a free-text description of what to build (playing the same role as the hand-typed `task` input a Build Run takes today), and an optional cost-cap override (defaults to the standard per-Build-Run cap and may not exceed the configured ceiling). The submitter edits and discusses the issue freely — title, body, comments — until it's ready.

**Trigger: the `ready-for-staging` label.** Adding it to an `intake`-labelled issue fires a GitHub Actions workflow (`issues: labeled`) that kicks off App Staging — not issue creation itself, so the Intake Spec can be iterated on first. The workflow refuses (commenting why) if another `intake` issue is already past this label, or a Build Run is in flight: v1 runs one Managed App through Intake → App Staging → Build Run at a time. This is a deliberate stepping stone, not a durable limit — lifting it, and extending Intake to ongoing feature/bug work against already-existing Managed Apps, is expected to be the Orchestrator's next real destination once a single new Managed App has been proven end-to-end.

On success, the Intake issue is closed with a comment linking the new Managed App's repo.
→ [issue #17](https://github.com/ojones/ai-factory/issues/17)

## Deployment provisioning

**App Staging** creates only the baseline of a new Managed App — repo, seeded code, secrets — then hands off. Coding, review, and deployment all happen afterward, in Build Runs.

**Credential: one fine-grained personal access token**, scoped to the owner's personal GitHub account with **no expiration**, stored as an Actions secret in ai-factory. A GitHub App installation was the earlier pin but cannot work: installation tokens get `403 Resource not accessible by integration` on `POST /user/repos` for personal accounts, so repo creation — the first step of every App Staging run — is blocked (findings: [issue #20](https://github.com/ojones/ai-factory/issues/20)). The PAT must cover repository creation, contents, workflows (to push the seeded `.github/workflows/` files), secrets write, and actions (to dispatch); confirmed working end to end in App Staging (issue #31): repo creation, secrets write, a contents push that includes `.github/workflows/`, and a workflow dispatch. A fine-grained PAT cannot be created or rotated by API, so changing it is a manual step. **Accepted tradeoff:** repo creation forces "All repositories" scope, so the PAT can also write secrets in ai-factory and any other repo the owner has. A separate dedicated GitHub account to contain this was considered and rejected for v1 (one owner; extra identity to maintain). A GitHub org (which would make the App route work) was rejected for the same setup-cost reason; revisit if collaborators are added.

**Repos**: public, under the owner's personal account, named from the Intake issue title. Public means unlimited Actions minutes and plain GHCR pulls.

**Seeding**: the Starter Template stays in this monorepo at `templates/starter/` as the single source of truth — no separate template repo. App Staging creates an empty repo, writes the tracked files of `templates/starter/` (via `git archive`, never the working directory, so ignored files like `node_modules` can't leak in), adds `INTAKE.md` (the Intake Spec as submitted, a link to the Intake issue, and the cost cap used — a snapshot, never edited afterward), and makes one initial commit.

**Secrets pushed into the new repo**: `FLY_API_TOKEN` (the single shared Fly org-level token), `GROWTHBOOK_CLIENT_KEY` (see [Feature-flag infrastructure](#feature-flag-infrastructure)), and `PREVIEW_TOKEN`. The preview token is derived as `HMAC(master secret held in ai-factory, app slug)` rather than stored per app, because GitHub secrets are write-only: the Build Run recomputes it to exercise a dark feature, with no per-app storage. No DeepInfra credential is pushed: the Build Run workflow lives in ai-factory, checks out the Managed App repo with the PAT, and mints each run's capped credential in the same job, so the DeepInfra parent key never leaves ai-factory and never reaches an agent's environment.

**Fly app**: not created by App Staging. `fly/provision.sh` creates it idempotently on first deploy, deriving the name from the repo name ([STANDARDS-DEPLOYMENT.md](STANDARDS-DEPLOYMENT.md#starter-template-contents-workflows-and-fly-config)).

**Idempotency**: every step is check-then-act, so App Staging is safely re-runnable by re-adding the `ready-for-staging` label after a partial failure. Repo ownership is proven by a marker in the repo description, `Intake: ojones/ai-factory#<N>`. A rerun adopts an existing repo only if the marker matches this Intake issue; any other pre-existing repo with that name (including `ai-factory` itself) is a hard stop, with an explanatory comment on the Intake issue, and nothing is ever overwritten. Any failed or refused run comments on the Intake issue and removes `ready-for-staging`, since re-adding a label that is still present would not fire the workflow. The seed push is also the first deploy: it triggers the new repo's Test Gate → Build → Deploy chain, so its secrets and kill switch are created first.

**Handoff**: App Staging's last step dispatches the Build Run workflow with only the Intake issue number and app name. The Build Run reads the task and cost-cap override from the issue body when it starts and snapshots it, so later edits don't affect a run in flight. The Intake issue then closes (see [Intake](#intake)).
→ [issue #20](https://github.com/ojones/ai-factory/issues/20), [issue #23](https://github.com/ojones/ai-factory/issues/23)

## Feature-flag infrastructure

**Tool: [GrowthBook](https://www.growthbook.io)** (MIT core), with Managed App code written against **OpenFeature** rather than GrowthBook's SDK directly. Runner-up: Unleash.
→ [issues/16](.scratch/orchestrator-spec/issues/16-which-feature-flag-tool.md)

**Hosting**: one shared, always-on GrowthBook instance — not one per Managed App — backed by a managed MongoDB Atlas free-tier cluster (GrowthBook requires MongoDB, not Postgres). The Orchestrator holds one manually-created, admin-scoped GrowthBook Personal Access Token (a one-time setup exception to full automation, since GrowthBook's API can't create admin keys itself).

**Per-Managed-App isolation**: self-hosted GrowthBook's free/OSS tier caps at 1 project per organization — confirmed empirically (`402` on a second `POST /v1/projects` call) and corroborated by GrowthBook's own pricing page. Every Managed App shares that one project; App Staging no longer creates a project per app. Multi-org mode (`IS_MULTI_ORG`) was considered and rejected: its self-hosted licensing status is unresolved in GrowthBook's own docs (described as a free env var, yet "Multi-tenant Mode" is marketed Self-Hosted-Enterprise-only), and — decisively — GrowthBook exposes no REST API to create organizations programmatically, only a manual/UI join flow, which would break one-call automation regardless of licensing. Paid Self-Hosted Enterprise was rejected as sales-quote-only with no disclosed price. Running a separate GrowthBook instance per Managed App was rejected: the Factory wants one shared data source, and per-app instances aren't free (each needs its own running service + MongoDB cluster). Switching feature-flag tools entirely was rejected too: every other self-hostable OSS alternative (Unleash, Flagsmith, PostHog) converges on the same 1-project-per-free-instance cap, and the one exception found (Flipt) carries a non-OSI "Fair Source" license, a worse tradeoff than GrowthBook's MIT core plus this app-naming workaround. → [Decide GrowthBook per-Managed-App flag isolation (#22)](https://github.com/ojones/ai-factory/issues/22).

Isolation between Managed Apps is therefore by **flag-key naming only**, not by any GrowthBook access boundary — every Managed App's SDK connection key can technically fetch every other app's flag payload. This is an accepted tradeoff for this personal project, not an oversight. See [STANDARDS-FEATURE-FLAGS.md](STANDARDS-FEATURE-FLAGS.md#code-wiring) for the naming convention this forces.

During App Staging, the Orchestrator calls GrowthBook's REST API once to create an app-scoped, read-only SDK connection key, named for the app, against the single shared project (no project creation call anymore), and pushes it into the new repo's secrets alongside the Fly token. On a rerun after a partial failure, any existing key with that name is revoked and a fresh one minted and re-pushed. In the same step it creates the app's `<app-slug>.global-kill-switch` flag in GrowthBook and turns it **on** if it doesn't already exist (never touching an existing one, so an owner's manual off sticks). This is required, not optional: the kill switch fails closed, so until the flag exists and is on, a new Managed App serves only its maintenance response. One key per Managed App is still minted — it buys no isolation, but keeps revocation, rotation, and GrowthBook's own per-connection usage view organized per app.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [#22](https://github.com/ojones/ai-factory/issues/22)
