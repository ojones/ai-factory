Type: grilling
Status: resolved

## Question

Should the Orchestrator run as an always-on VM/container, or as ephemeral compute spun up only for the duration of a Build Run and torn down after?

## Answer

Ephemeral. "Runs overnight for as long as it needs" implies a bounded run, not infinite idle; paying only while a Build Run is active is strictly cheaper and simpler to reason about for cost control. The specific ephemeral compute platform is deferred to [Which ephemeral compute platform for the Orchestrator](../issues/09-which-compute-platform.md).
