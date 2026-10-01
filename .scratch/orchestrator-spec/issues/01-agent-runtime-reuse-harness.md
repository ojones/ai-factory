Type: grilling
Status: resolved

## Question

Should an Agent (per GLOSSARY.md) be an existing open-source CLI coding-agent harness wrapped by the Orchestrator, or a fully custom LLM loop built from scratch?

## Answer

Reuse an existing open-source harness rather than building a custom loop. Matches the "lean open source" preference and shrinks the eventual build scope — a custom agent loop would be reinventing a solved problem. The specific harness is deferred to [Which open-source agent harness](../issues/07-which-agent-harness.md).
