# Advice for the Orchestrator

Three documents written outside this repo (October 2026) about how coding-agent work should be planned, dispatched and verified. They are built on OpenHands' published posts and the practices those posts cite. Copies are kept here unchanged:

- [MANAGER.md](MANAGER.md): instructions for a planning and coordination manager agent.
- [openhands-planning-guide.md](openhands-planning-guide.md): turning requirements into dependency-aware GitHub issues and verified delivery.
- [verification-tools-for-coding-agents.md](verification-tools-for-coding-agents.md): which verification tools fit a reviewer and tester agent.

## How to read them

They are **advisory**. They were written for a generic manager and coding agents on one application, and do not know this Factory's purpose: unattended Build Runs that create and update many Managed Apps, with the update's flag as the test-in-production mechanism. Where they conflict with [ARCHITECTURE.md](../../ARCHITECTURE.md) or the [Standards](../../STANDARDS.md), those win unless a decision says otherwise and records why.

Their vocabulary differs from ours. The mapping is in [GLOSSARY.md](../../GLOSSARY.md) (see *Change-set gate*); the short version: their "change set" is one Build Run's work on one update, their "change-set gate" is the update's flag, their "manager" is the Orchestrator, their "ask the user" is a needs-human Issue.

[ADOPTION.md](ADOPTION.md) lists every recommendation and what we did with it. The reasoning and the larger plan are in [.wayfinder/orchestrator-hardening/source-plan.md](../../.wayfinder/orchestrator-hardening/source-plan.md).

The URLs and benchmark figures in the documents were not re-verified when they were copied here.
