Type: research
Status: resolved

## Question

Given the Orchestrator will reuse an existing open-source coding-agent harness rather than a custom loop (see [Agent runtime decision](01-agent-runtime-reuse-harness.md)), which harness should an Agent be built on?

Compare candidates (e.g. OpenHands, Aider, SWE-agent, and any other actively maintained open-source CLI coding-agent harness) against:
- License (must permit the Factory's use)
- Support for pluggable/OpenAI-compatible model backends (needed to use whichever open-weight model API provider gets picked separately)
- Tool-calling / agentic reliability in practice, not just on paper
- Maintenance activity and community health
- Ease of non-interactive, unattended invocation (no TUI/human-in-the-loop requirement) for an overnight Build Run

Recommend one, with the runner-up and why it lost.

## Answer

**OpenHands** (All-Hands-AI/OpenHands, MIT): clean on every criterion — MIT license, LiteLLM-based pluggable/OpenAI-compatible backends with documented open-weight setups, SOTA-class SWE-bench Verified results, company-backed active maintenance, and a purpose-built `--headless` CLI mode with `--json` structured output (which doubles as a feed for the visibility requirement).

Runner-up: **mini-swe-agent** — actively-maintained, headless-by-design, but its ~100-line minimalism would push tool-suite and observability scaffolding back onto the Factory, cutting against the point of reusing a harness, and it lacks OpenHands' production maturity.

Also ruled out: Goose (no comparable SWE-bench-style reliability evidence), Aider (de facto single-maintainer, ~4 months stale as of research date — unacceptable bus-factor risk for a long-running dependency).

Full findings with citations: see branch `research/agent-harness`, file `.scratch/orchestrator-spec/research/agent-harness.md` (commit 2f6b05f).
