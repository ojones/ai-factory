# Agent configuration

The editable configuration for the Orchestrator's Agents, kept apart from the architecture and Standards so it can be tuned over time without touching them. Roles and stage order are defined in [ARCHITECTURE.md](../ARCHITECTURE.md#agents-and-build-run-stages); this directory holds only what is expected to change.

- [profiles.yml](profiles.yml): which model, endpoint, and prompt each role uses, plus the run limits. Switching a role's model or the provider is an edit here and nowhere else.
- `prompts/<role>.md`: one role prompt per Agent (`coder`, `reviewer`, `tester`, `pipeline`), each edited independently. Not yet authored; see the prompt-authoring ticket.

The Build Run workflow reads these files from ai-factory at run time. They are never copied into a Managed App repo, so the coder can't edit its reviewer's instructions, and changes apply to the next Build Run without touching any Managed App.

A model is only eligible for a role if DeepInfra (or whichever provider is configured) serves it on an OpenAI-compatible API and returns per-response `usage.estimated_cost`, because the cost guardrail depends on that field. Smoke-test a new model against it before pinning.
