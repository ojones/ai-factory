Type: grilling
Status: resolved

## Question

Since Build Runs happen unattended overnight, should the spec mandate a minimum observability/reporting requirement (Orchestrator must leave a summary of what happened and surface failures) as part of the architecture, even though the implementation (e.g. a dashboard) is not being built here?

## Answer

Yes, included as a required Standards concern. Trusting an unattended system hinges on being able to find out what it did; this is cheap to spec now as a requirement even though the implementation is deferred. Design is deferred to [Build Run visibility/reporting standard](../issues/13-visibility-standard-design.md).
