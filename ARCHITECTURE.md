# Orchestrator Architecture

Decisions about how the Orchestrator itself is built and operated — for whoever implements the v1 Orchestrator. Distinct from [STANDARDS.md](STANDARDS.md): nothing here is something a Managed App's own code needs to follow. Terminology follows [GLOSSARY.md](GLOSSARY.md).

Each decision links back to its ticket in `.scratch/orchestrator-spec/issues/` for the full comparison, runner-ups, and citations.

## Agent runtime

The Orchestrator reuses an existing open-source CLI coding-agent harness rather than a custom LLM loop — shrinks build scope and matches the Factory's open-source lean.

**Harness: [OpenHands](https://github.com/All-Hands-AI/OpenHands)** (MIT). SWE-bench-leading, pluggable to open-weight models via LiteLLM, purpose-built `--headless` CLI mode with `--json` structured output. Runner-up: mini-swe-agent.
→ [issues/01](.scratch/orchestrator-spec/issues/01-agent-runtime-reuse-harness.md), [issues/07](.scratch/orchestrator-spec/issues/07-which-agent-harness.md)

## Model serving

Open-weight model inference is consumed via a pay-per-token API, not self-hosted GPU inference — Build Runs are bounded, not continuously GPU-saturated, so idle self-hosted cost would dominate.

**Provider/model: [DeepInfra](https://deepinfra.com) serving `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo`** (Apache 2.0). Cheapest confirmed per-token price for a model RL-trained for long multi-turn tool-calling agentic loops; leads open-weight models on agentic tool-use benchmarks. Runner-up: Together AI (same model).
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

**Enforcement mechanism**: the cap covers LLM token spend only (not GitHub Actions minutes or other metered calls). The Orchestrator sums the `usage.estimated_cost` field DeepInfra returns on every chat-completion response and compares the running total to the per-run cap after every LLM call. On breach, the current turn finishes cleanly and the next turn is simply refused — never a mid-call abort. As a provider-side second line of defense, each Build Run is issued its own scoped API credential (a JWT with an embedded max-USD limit equal to that run's own cap).
→ [issues/05](.scratch/orchestrator-spec/issues/05-cost-guardrails-mechanism-not-numbers.md), [issues/14](.scratch/orchestrator-spec/issues/14-cost-guardrail-design.md)

## Visibility

A minimum observability/reporting requirement for unattended Build Runs is part of the architecture.

**Mechanism**: a **Build Run Summary** written to `GITHUB_STEP_SUMMARY` (status, what changed, test results, cost spent, deploy outcome + a link to that deployment's Fly log viewer). The raw OpenHands `--json` JSONL event stream is uploaded as a build artifact for deep-dive debugging. A curated, machine-readable **Build Run Report** (same fields as the Summary) is produced alongside it for future tooling. On failure — a crash, or the cost/time budget exhausted before CI went green — an explicit workflow step auto-creates a GitHub Issue in the Managed App's repo, distinguishing which.
→ [issues/06](.scratch/orchestrator-spec/issues/06-visibility-in-scope.md), [issues/13](.scratch/orchestrator-spec/issues/13-visibility-standard-design.md)

## Intake

A Managed App's build begins with an **Intake** issue — a GitHub Issue Form on this repo (ai-factory) labelled `intake`, titled the Managed App's name (kebab-cased for the eventual repo name), carrying two fields: a free-text description of what to build (playing the same role as the hand-typed `task` input a Build Run takes today), and an optional cost-cap override (defaults to the standard per-Build-Run cap). The submitter edits and discusses the issue freely — title, body, comments — until it's ready.

**Trigger: the `ready-for-staging` label.** Adding it to an `intake`-labelled issue fires a GitHub Actions workflow (`issues: labeled`) that kicks off App Staging — not issue creation itself, so the Intake Spec can be iterated on first. The workflow refuses (commenting why) if another `intake` issue is already past this label, or a Build Run is in flight: v1 runs one Managed App through Intake → App Staging → Build Run at a time. This is a deliberate stepping stone, not a durable limit — lifting it, and extending Intake to ongoing feature/bug work against already-existing Managed Apps, is expected to be the Orchestrator's next real destination once a single new Managed App has been proven end-to-end.

On success, the Intake issue is closed with a comment linking the new Managed App's repo.
→ [issue #17](https://github.com/ojones/ai-factory/issues/17)

## Deployment provisioning

**App Staging** creates only the baseline of a new Managed App — repo, seeded code, secrets — then hands off. Coding, review, and deployment all happen afterward, in Build Runs.

**Credential: one fine-grained personal access token**, scoped to the owner's personal GitHub account with **no expiration**, stored as an Actions secret in ai-factory. A GitHub App installation was the earlier pin but cannot work: installation tokens get `403 Resource not accessible by integration` on `POST /user/repos` for personal accounts, so repo creation — the first step of every App Staging run — is blocked (findings: [issue #20](https://github.com/ojones/ai-factory/issues/20)). The PAT must cover repository creation, contents, workflows (to push the seeded `.github/workflows/` files), secrets write, and actions (to dispatch); exact scope names to be confirmed at build time. A fine-grained PAT cannot be created or rotated by API, so changing it is a manual step. **Accepted tradeoff:** repo creation forces "All repositories" scope, so the PAT can also write secrets in ai-factory and any other repo the owner has. A separate dedicated GitHub account to contain this was considered and rejected for v1 (one owner; extra identity to maintain). A GitHub org (which would make the App route work) was rejected for the same setup-cost reason; revisit if collaborators are added.

**Repos**: public, under the owner's personal account, named from the Intake issue title. Public means unlimited Actions minutes and plain GHCR pulls.

**Seeding**: the Starter Template stays in this monorepo at `templates/starter/` as the single source of truth — no separate template repo. App Staging creates an empty repo, writes the tracked files of `templates/starter/` (via `git archive`, never the working directory, so ignored files like `node_modules` can't leak in), adds `INTAKE.md` (the Intake Spec as submitted, a link to the Intake issue, and the cost cap used — a snapshot, never edited afterward), and makes one initial commit.

**Secrets pushed into the new repo**: `FLY_API_TOKEN` (the single shared Fly org-level token) and `GROWTHBOOK_CLIENT_KEY` (see [Feature-flag infrastructure](#feature-flag-infrastructure)). No DeepInfra credential is pushed: the Build Run workflow lives in ai-factory, checks out the Managed App repo with the PAT, and mints each run's capped credential in the same job, so the DeepInfra parent key never leaves ai-factory and never reaches an agent's environment.

**Fly app**: not created by App Staging. `fly/provision.sh` creates it idempotently on first deploy, deriving the name from the repo name ([STANDARDS-DEPLOYMENT.md](STANDARDS-DEPLOYMENT.md#starter-template-contents-workflows-and-fly-config)).

**Idempotency**: every step is check-then-act, so App Staging is safely re-runnable by re-adding the `ready-for-staging` label after a partial failure. Repo ownership is proven by a marker in the repo description, `Intake: ojones/ai-factory#<N>`. A rerun adopts an existing repo only if the marker matches this Intake issue; any other pre-existing repo with that name (including `ai-factory` itself) is a hard stop, with an explanatory comment on the Intake issue, and nothing is ever overwritten.

**Handoff**: App Staging's last step dispatches the Build Run workflow with only the Intake issue number and app name. The Build Run reads the task and cost-cap override from the issue body when it starts and snapshots it, so later edits don't affect a run in flight. The Intake issue then closes (see [Intake](#intake)).
→ [issue #20](https://github.com/ojones/ai-factory/issues/20), [issue #23](https://github.com/ojones/ai-factory/issues/23)

## Feature-flag infrastructure

**Tool: [GrowthBook](https://www.growthbook.io)** (MIT core), with Managed App code written against **OpenFeature** rather than GrowthBook's SDK directly. Runner-up: Unleash.
→ [issues/16](.scratch/orchestrator-spec/issues/16-which-feature-flag-tool.md)

**Hosting**: one shared, always-on GrowthBook instance — not one per Managed App — backed by a managed MongoDB Atlas free-tier cluster (GrowthBook requires MongoDB, not Postgres). The Orchestrator holds one manually-created, admin-scoped GrowthBook Personal Access Token (a one-time setup exception to full automation, since GrowthBook's API can't create admin keys itself).

**Per-Managed-App isolation**: self-hosted GrowthBook's free/OSS tier caps at 1 project per organization — confirmed empirically (`402` on a second `POST /v1/projects` call) and corroborated by GrowthBook's own pricing page. Every Managed App shares that one project; App Staging no longer creates a project per app. Multi-org mode (`IS_MULTI_ORG`) was considered and rejected: its self-hosted licensing status is unresolved in GrowthBook's own docs (described as a free env var, yet "Multi-tenant Mode" is marketed Self-Hosted-Enterprise-only), and — decisively — GrowthBook exposes no REST API to create organizations programmatically, only a manual/UI join flow, which would break one-call automation regardless of licensing. Paid Self-Hosted Enterprise was rejected as sales-quote-only with no disclosed price. Running a separate GrowthBook instance per Managed App was rejected: the Factory wants one shared data source, and per-app instances aren't free (each needs its own running service + MongoDB cluster). Switching feature-flag tools entirely was rejected too: every other self-hostable OSS alternative (Unleash, Flagsmith, PostHog) converges on the same 1-project-per-free-instance cap, and the one exception found (Flipt) carries a non-OSI "Fair Source" license, a worse tradeoff than GrowthBook's MIT core plus this app-naming workaround. → [Decide GrowthBook per-Managed-App flag isolation (#22)](https://github.com/ojones/ai-factory/issues/22).

Isolation between Managed Apps is therefore by **flag-key naming only**, not by any GrowthBook access boundary — every Managed App's SDK connection key can technically fetch every other app's flag payload. This is an accepted tradeoff for this personal project, not an oversight. See [STANDARDS-FEATURE-FLAGS.md](STANDARDS-FEATURE-FLAGS.md#code-wiring) for the naming convention this forces.

During App Staging, the Orchestrator calls GrowthBook's REST API once to create an app-scoped, read-only SDK connection key, named for the app, against the single shared project (no project creation call anymore), and pushes it into the new repo's secrets alongside the Fly token. On a rerun after a partial failure, any existing key with that name is revoked and a fresh one minted and re-pushed. One key per Managed App is still minted — it buys no isolation, but keeps revocation, rotation, and GrowthBook's own per-connection usage view organized per app.
→ [issues/18](.scratch/orchestrator-spec/issues/18-feature-flag-standards-content.md), [#22](https://github.com/ojones/ai-factory/issues/22)
