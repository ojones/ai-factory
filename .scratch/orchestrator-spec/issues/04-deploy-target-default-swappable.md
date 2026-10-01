Type: grilling
Status: resolved

## Question

Should the deployment Standards mandate a single fixed hosting target for every Built Application, or just pin the mechanism (Docker image + GitHub Actions + registry) and leave the compute target configurable per app?

## Answer

Pin one default target for v1 simplicity, but the deployment mechanism must not hardcode an assumption that the target is fixed forever: it must stay swappable to a different hosting option on a project-by-project basis as the need arises. The specific default target is deferred to [Which default deploy target for Built Applications](../issues/10-which-deploy-target.md), and the swappability requirement must be carried into [Deployment Standards content](../issues/12-deployment-standards-content.md).
