---
title: Build the secrets workflow decided in ticket 13
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

Ticket 13 decided how a Managed App's third-party secret is handled and built none of it. Build it: a request that needs a secret stops after the planner as `awaiting_secret` with the exact `gh secret set` command on the Intake, and builds only once the declared names exist as GitHub Actions secrets on the app's repo; the deploy job copies them to Fly; no Agent or artifact ever holds a value. Which slice goes first, and what is the smallest end-to-end version that can be proven with a throwaway secret name?

## Added context

- The decisions, the defaults the owner has not seen, and the full list of what to build are in the Resolution of [13-secrets-management-workflow.md](13-secrets-management-workflow.md). Read it first.
- Build list from that ticket: `triage.py` and `planner.py` (a structured `secrets` list; `awaiting_secret` replaces the `secrets` refusal, and `finalize` must treat it like `refused`, not as an OK ending, because INV-24 makes OK endings close the Intake); the start-of-run `gh secret list` check in `build_run.py`; `secrets.json` and the deploy workflow's copy step in the Starter Template (then template sync gives it to existing apps); the reviewer rubric item and a scan of every coder diff and of the artifacts for secret shapes before they are pushed or uploaded; GitHub secret scanning with push protection switched on in `stage.sh`; a daily pass listing secrets older than 90 days and orphans; a golden Intake for a keyed request in `docs/golden-intakes.md`; invariants for no value reaching an Agent or an artifact, nothing built before the names exist, and a coder diff with a secret shape never being pushed.
- One live check before relying on it: that the deploy workflow's copy step really masks and delivers a value (use a throwaway name).
- Related: ticket 06 (triage, INV-40), the pre-push review gate (the diff scan sits there), the retrospective's isolation (INV-45), and the owner's preference for GitHub-native free tools.

## Resolution (2026-10-14)

First slice built and unit-tested; **not proven live** (the throwaway-secret check in the ticket is still to do, see ticket 31).

**Built.** The smallest end-to-end path:
- `planner.md` / `planner.py`: a structured `secrets` list (name, purpose, read_by), validated (capitals-and-underscores names, the Factory's own names and `GITHUB_*`/`FLY_*` refused, purpose required, unique). `secrets` is no longer a refusal category in the prompt; a pasted value is still refused at the start (INV-40).
- `build_run.py`: `require_secrets` (after the planner, `gh secret list` names only) ends `awaiting_secret` through `AwaitingSecret`, with the exact `gh secret set` commands on the Intake; `ANSWERED_ENDINGS = (refused, awaiting_secret)` is excluded from failure handling in `finalize`, `is_dark_broken`, and the retrospective (fix request, stuck issue, early return); INV-24 holds because it is not an OK ending. The coder gets a note that the secrets exist as `process.env.<NAME>`.
- `secret_problem`: a coder commit that adds a real secret value (specific shapes only: private key, GitHub/AWS/sk-/Slack tokens, JWT) is discarded and never pushed; a `secrets.json` name the plan did not declare is rejected.
- Starter: `secrets.json` (empty) and a protected deploy step that copies only declared names from the GitHub secrets to Fly through `flyctl secrets import --stage` on stdin, refuses reserved names, and fails if a value is missing.
- `stage.sh`: GitHub secret scanning with push protection on every repo it creates or adopts (a warning, not a failure, if it cannot).
- Coder prompt, reviewer rubric item, golden Intake, ARCHITECTURE "Secrets", INV-48 to INV-50 with tests.

**Decisions made here.** Only update Intakes are covered (the planner does not run on a first build, and a first build that needs a key is built without it). A multi-change-set plan stops before filing any children, and each child carries the secrets note. The diff scan leaves out the "password = ..." shape, which ordinary code is full of.

**Left for ticket 31:** the live check that the deploy step masks and delivers a throwaway value, and that the Orchestrator's PAT can run `gh secret list` on an app repo (it may need the Secrets read permission; if not, the run stops as needs-human, "could not read the names of the app's GitHub secrets"); the scan of the Report, event streams and artifacts for secret shapes before upload; the daily pass listing secrets older than 90 days and orphans; skipping a retry whose errors point at authentication; the `secret-leak` issue; a line in the teardown skill.

**Added the same day (owner request): the check comes before any spend.** The declared names are recorded on the Intake (hidden `factory-secrets` comment marker, and `secrets` in each child issue's plan metadata), and `setup` checks them with `gh secret list` before the planner, coder, reviewer or tester runs, on every start: re-runs, retries and every child of a plan. The one unavoidable spend before the first check is the planner call that discovers the need (about $0.05). A planner that declares a name not yet recorded is checked before the coder too.

**Found live (2026-10-15):** the first deploy step read the secrets with `toJSON(secrets)`. GitHub marked every Deploy run `action_required` ("GitHub detected that this workflow file may be malicious"), so nothing deployed. It now lists each declared name as a static `NAME: ${{ secrets.NAME }}` line, written by the Orchestrator between markers (`wire_secrets`, `stage_secret_wiring`, and `copy_template_files` keeps the lines when sync copies the file over). The run also showed the coder rejection for an undeclared `secrets.json` name working live.
