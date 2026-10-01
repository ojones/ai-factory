Type: research
Status: claimed

## Question

Given the Orchestrator will reuse an existing open-source coding-agent harness rather than a custom loop (see [Agent runtime decision](01-agent-runtime-reuse-harness.md)), which harness should an Agent be built on?

Compare candidates (e.g. OpenHands, Aider, SWE-agent, and any other actively maintained open-source CLI coding-agent harness) against:
- License (must permit the Factory's use)
- Support for pluggable/OpenAI-compatible model backends (needed to use whichever open-weight model API provider gets picked separately)
- Tool-calling / agentic reliability in practice, not just on paper
- Maintenance activity and community health
- Ease of non-interactive, unattended invocation (no TUI/human-in-the-loop requirement) for an overnight Build Run

Recommend one, with the runner-up and why it lost.
