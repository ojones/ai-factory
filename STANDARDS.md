# Standards

The authored conventions Agents must follow when producing a Managed App, per [GLOSSARY.md](GLOSSARY.md). Distinct from [ARCHITECTURE.md](ARCHITECTURE.md): everything here is something a Managed App's own code must actually do, not how the Orchestrator itself is built or operated.

- **[Coding](STANDARDS-CODING.md)** — the pinned application stack, repo/Starter Template conventions, test gate, style, git workflow, secrets handling, dependency policy.
- **[Deployment](STANDARDS-DEPLOYMENT.md)** — containerization, registry/tagging, the build/deploy workflow split.
- **[Visibility](STANDARDS-VISIBILITY.md)** — runtime logging and error-handling conventions.
- **[Feature flags](STANDARDS-FEATURE-FLAGS.md)** — flagging policy, the mandatory kill switch, code-wiring conventions.

Each rule here links back to its originating ticket in `.scratch/orchestrator-spec/issues/` for the full reasoning, alternatives considered, and citations.
