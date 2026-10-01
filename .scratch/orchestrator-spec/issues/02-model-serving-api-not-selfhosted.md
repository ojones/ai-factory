Type: grilling
Status: resolved

## Question

Should open-weight model inference be self-hosted (own/rented GPU running something like vLLM) or consumed via a pay-per-token API provider that hosts open-weight models?

## Answer

Pay-per-token API hosting. Build Runs are bounded, not continuously GPU-saturated, so idle self-hosted GPU cost would dominate; per-token billing matches the cost-conscious constraint better than owning idle compute. The specific provider and model are deferred to [Which API provider + open-weight model](../issues/08-which-model-provider.md).
