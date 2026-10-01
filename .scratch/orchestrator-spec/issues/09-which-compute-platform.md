Type: research
Status: resolved

## Question

Given the Orchestrator should run as ephemeral compute rather than an always-on service (see [Orchestrator host decision](03-orchestrator-host-ephemeral.md)), which platform should host it during a Build Run?

Compare candidates (e.g. GitHub Actions itself as the runner, Fly Machines, Modal, AWS Fargate/Lambda, and any other pay-per-use ephemeral compute option) against:
- Cost structure (per-second/per-minute billing, free tier if any)
- Maximum single-run duration (a Build Run may need to run for hours overnight — does the platform allow this?)
- Ease of triggering/scheduling an overnight run
- Secrets handling (API keys for the model provider and for deploying Built Applications)
- Native run logging (feeds into the visibility requirement — see [Visibility decision](06-visibility-in-scope.md))

Recommend one, with the runner-up and why it lost.

## Answer

**GitHub Actions (GitHub-hosted runners)**: scheduling (native `on.schedule` cron), secrets (native encrypted secrets), and native run logging/visibility all come for free with zero extra infrastructure; clears the 6-hour-per-job duration bar for an overnight run; bills per-minute with no idle cost; and piggybacks on infrastructure the Factory already needs for deployment Standards rather than requiring a second platform account.

Runner-up: **Fly Machines** — comparable per-second cost and a clean secrets model, but its built-in scheduler only supports fixed hourly/daily/weekly/monthly intervals (true cron needs a separate community blueprint), and secrets/logs live in a separate dashboard rather than alongside the workflow definition.

Also ruled out: AWS Lambda (hard 15-min timeout, 90-min max on the extended tier — disqualifying for an hours-long run), Modal (GPU/inference-centric pricing and tooling buys nothing extra here), AWS Fargate (no duration ceiling, but needs EventBridge Scheduler + explicit `awslogs` config bolted on for capabilities the others give natively).

Full findings with citations: see branch `research/compute-platform`, file `.scratch/orchestrator-spec/research/compute-platform.md` (commit 878cbe2).
