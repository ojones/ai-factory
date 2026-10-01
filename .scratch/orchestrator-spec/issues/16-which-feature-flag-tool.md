Type: research
Status: resolved

## Question

The Factory's owner wants Built Applications to support testing changes in production via feature flags (gradual rollout / kill switch), not just blue-green or canary deploys at the infra layer. Which feature-flag tool should the deployment/coding Standards recommend for Built Applications? Compare popular, well-maintained, self-hostable open-source options (e.g. Unleash, Flagsmith, GrowthBook, PostHog feature flags, OpenFeature as a vendor-neutral SDK layer) against: self-hosting cost/complexity at small scale vs. a free/cheap hosted tier, SDK support, and fit with an Agent-driven, git-based workflow.

Recommend one, with the runner-up and why it lost.

## Answer

**GrowthBook**, with Built Application code written against **OpenFeature** (CNCF-graduated vendor-neutral SDK) rather than GrowthBook's SDK directly. GrowthBook's core is MIT-licensed with no artificial feature caps, self-hosts as a single app container + Postgres, and ships a REST API, a Terraform provider, and a purpose-built MCP server so an autonomous Agent can create/toggle/ramp flags without a human in a GUI — directly matching this Factory's unattended, Agent-driven operating model.

Runner-up: **Unleash** — larger community and SDK count, but its core is AGPLv3, its OSS self-hosted tier artificially caps at 1 project/2 environments (awkward for dev/stage/prod), and its client-side architecture needs a separate Proxy/Edge service whose OSS edition sunsets December 31, 2026.

Also notable: **Flagsmith** (BSD-3, lightest self-host footprint, strong Terraform/API story) — a reasonable swap-in if GrowthBook doesn't fit a specific project. **PostHog** feature flags ruled out as a default: its self-host infrastructure (ClickHouse/Kafka/Redis/MinIO, 4vCPU/16GB minimum) is disproportionate if adopted for flags alone.

Full findings with citations: see branch `research/feature-flags`, file `.scratch/orchestrator-spec/research/feature-flags.md` (commit f801457).
