Type: research
Status: resolved
Blocked by: 11

## Question

[Coding Standards content](11-coding-standards-content.md) decided every Built Application is built on one pinned language/framework stack (backend + frontend), seeded from a fixed [Starter Template](../../GLOSSARY.md), rather than a stack chosen fresh per project. Which specific stack should be pinned?

Compare candidates against:
- License (must permit the Factory's use; no copyleft/field-of-use issues)
- LLM training-data representation — how reliably OpenHands' chosen model (Qwen3-Coder-480B-A35B-Instruct-Turbo, per [issue 08](08-which-model-provider.md)) can generate and modify code in it, since Agents write and maintain this code unattended
- Fit with the deploy shape already fixed in [Deployment Standards content](12-deployment-standards-content.md): one container, backend serves the built frontend's static assets, no separate frontend container
- Fit with Fly.io ([issue 10](10-which-deploy-target.md)) and GrowthBook/OpenFeature ([issue 16](16-which-feature-flag-tool.md)) SDK availability
- Maintenance activity and community health, same bar applied to the harness/model picks

Recommend one backend framework + one frontend framework (same language where reasonable), with the runner-up and why it lost.

## Answer

**Express (backend) + React (frontend), both in TypeScript** — a single Node.js/TypeScript codebase per Built Application, frontend built via Vite to a static `dist/` directory served directly by Express's built-in `express.static()` middleware, matching ticket 12's one-container deploy shape as a one-line integration. TypeScript (not plain JS) is the pinned language: GitHub's own Octoverse 2025 report states TypeScript overtook Python and JavaScript as GitHub's most-used language in August 2025, citing a study that 94% of LLM-generated compilation errors were type-check failures and that typed languages make agent-assisted coding more reliable in production.

Only JS/TS pairs a competitive backend framework with a genuine frontend-framework ecosystem — Python/Go/Java have strong backend frameworks but no equivalent to React for building a real product UI, so any cross-language alternative forces a second language into every Built Application for no offsetting benefit. Express and React are each their ecosystem's dominant, most battle-tested choice (MIT-licensed, pushed same-day, ~9–29x their nearest same-language competitor's weekly npm downloads), which doubles as a proxy for training-data density for the pinned Qwen3-Coder-480B model. OpenFeature's server, web, and React SDKs are all stable 1.x, giving complete frontend-to-backend flag coverage.

One caveat: GrowthBook's own JS/web OpenFeature *provider* package (as opposed to the OpenFeature SDKs themselves) is community-maintained and pre-1.0, unlike GrowthBook's first-party Python/Go/Java/.NET providers — a contained risk since it just wraps GrowthBook's own stable JS SDK.

**Runner-up: FastAPI (Python) + React (TypeScript)** — strong on every other axis (MIT, very active, Python has the stronger independently-verified SWE-bench Verified signal for this exact model — that benchmark is built entirely from 12 Python repos — plus a first-party GrowthBook OpenFeature provider), but loses on the same-language framing: it forces two languages into every Built Application where Node.js alone covers the whole stack with no corresponding loss. Documented fallback if a future Built Application's domain specifically favors Python (e.g. heavy data/ML work).

Also ruled out: Fastify/NestJS as the backend default (both lose to Express on ecosystem dominance despite being fully viable — reasonable per-project swaps if schema validation becomes a real pain point), Vue/Svelte as the frontend default (lose to React on the same dominance margin; Svelte additionally carries version-churn risk from its Svelte 4→5 runes rewrite), Go backends (no frontend-framework counterpart, same cross-language drawback as Python without the offsetting SWE-bench/provider advantages), Next.js/Remix (a single fused framework, doesn't match "one backend + one frontend," worse fit for ticket 12's plain static-asset-serving shape than a dedicated backend + Vite-built SPA).

Full findings with citations: see branch `research/application-stack`, file `.scratch/orchestrator-spec/research/application-stack.md` (commit 46feecc).
