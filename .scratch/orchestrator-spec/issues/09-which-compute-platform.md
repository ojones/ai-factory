Type: research
Status: claimed

## Question

Given the Orchestrator should run as ephemeral compute rather than an always-on service (see [Orchestrator host decision](03-orchestrator-host-ephemeral.md)), which platform should host it during a Build Run?

Compare candidates (e.g. GitHub Actions itself as the runner, Fly Machines, Modal, AWS Fargate/Lambda, and any other pay-per-use ephemeral compute option) against:
- Cost structure (per-second/per-minute billing, free tier if any)
- Maximum single-run duration (a Build Run may need to run for hours overnight — does the platform allow this?)
- Ease of triggering/scheduling an overnight run
- Secrets handling (API keys for the model provider and for deploying Built Applications)
- Native run logging (feeds into the visibility requirement — see [Visibility decision](06-visibility-in-scope.md))

Recommend one, with the runner-up and why it lost.
