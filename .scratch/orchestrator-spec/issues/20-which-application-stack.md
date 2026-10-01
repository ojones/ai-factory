Type: research
Status: open
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
