---
title: Run Agents as a separate OS user
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

ARCHITECTURE.md records a known gap: Agents run as the same OS user as the Orchestrator, so a hostile or injected Agent could read the Orchestrator's process environment from `/proc` and find the PAT, the Fly token and the GrowthBook admin key. The pre-mortem says this must be closed before more than one app runs at a time. Decide and build how: a dedicated unprivileged user on the GitHub-hosted runner created in the workflow, with each Agent started through `sudo -u`, an explicit environment, and the working directories (app checkout, tester worktree, per-role HOME, artifacts) readable and writable by that user and nothing else.

## Added context

- Not built, deliberately: it cannot be tested from a laptop (it needs a Linux runner with sudo), a wrong permission setup would break every Build Run silently, and the invariant tests only cover the environment whitelist (INV-01), not process isolation.
- Where Agents start: `BuildRun.invoke` and `agent_env` in `orchestrator/build_run.py`; the checkout is made by `setup()`; the tester gets its own worktree; each role has its own HOME. The post-mortem Agent (`postmortem.py run_agent`) needs the same treatment.
- Find out first whether `/proc/<pid>/environ` of the Orchestrator is readable by another unprivileged user on `ubuntu-latest`: it normally is not, and if so the "known gap" is smaller than recorded (the real exposure is files the runner user can read, for example the git credential helper config and `GITHUB_*` files). Test that with a throwaway workflow before designing anything.
- A small acceptance test: an Agent-side command `cat /proc/$PPID/environ` and a read of the Orchestrator's files must fail, while a normal coder round still passes.

## Resolution

Probe (`isolation-probe.yml`, 2026-10-13): another account cannot read the runner user's `/proc/<pid>/environ`, `/home/runner` (750) or the Actions files; it can read any process's command line, so the git credential moved to `GIT_CONFIG_*` environment variables. Built: `agent` account created by the workflow, work dirs in `/srv/agent` shared via ACLs, Agents started through `sudo -n -u agent` with variables passed by name, kill through sudo by process group, a start-of-run self-check that stops the run if isolation does not hold (INV-34). Live: a full Build Run on `ojones-todo` (planner, coder, reviewer, tester with api-check) passed under isolation for $0.14. Not covered: the post-mortem Agent; an Agent can still read whatever its own account can (the app checkout); a daemonised Agent process can outlive its invocation.
