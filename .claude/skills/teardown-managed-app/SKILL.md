---
name: teardown-managed-app
description: Tear down a Managed App the Factory built (Fly app, GrowthBook SDK connection, GitHub repo). Use when the user wants a Managed App removed, retired or cleaned up, or asks what leftovers exist from failed or test Intakes.
---

# Tear down a Managed App

Removal is done by the `Teardown` workflow (`.github/workflows/teardown.yml`, script `infra/app-staging/teardown.sh`). Run it through `gh`; do not reimplement its steps by hand with `fly`, `gh repo delete` or `curl`. The script holds the safety checks (Intake marker on the repo, no Build Run in flight, Factory infrastructure refused). If it refuses, report why and stop.

The deletions are irreversible. The user must confirm each app by name in the current conversation, after seeing that app's dry-run plan. "Do one" or "do the first" is not a name: ask which app. Never infer approval from an earlier teardown, and never batch several apps under one confirmation.

## Steps

1. **Pick the app.** If the user named one, use it. Otherwise list candidates: Managed App repos are the ones whose description starts with `Intake: ojones/ai-factory#`.
   ```bash
   gh repo list ojones --limit 200 --json name,description,isArchived \
     -q '.[] | select(.description | startswith("Intake: ojones/ai-factory#")) | "\(.name)\t\(.description)"'
   ```
   For each, say which Intake it came from and the outcome of its last Build Run (`gh run list --workflow build-run.yml`). Let the user choose. Do not suggest an app that has a Build Run in flight.
2. **Dry run** (ask the user whether the repo should be deleted, the default, or archived, and pass `-f repo_action=archive` for the latter), always freshly run in this session even if an earlier one exists, because the app's state may have changed.
   ```bash
   gh workflow run teardown.yml -f app_name=<app> -f dry_run=true [-f repo_action=archive]
   gh run watch "$(gh run list --workflow teardown.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
   gh run view --log "$(gh run list --workflow teardown.yml --limit 1 --json databaseId -q '.[0].databaseId')"
   ```
   Show the user the outcomes table at the end of the log (Fly app, SDK connection, each flag, repo).
3. **Ask for confirmation** naming the app and what will be destroyed. If the app is live and released, say so, since its users lose the service.
4. **Real run**, only after a yes: the same commands with `-f dry_run=false`.
5. **Verify** each resource independently of the workflow's own log (`set -a; . ./.env; set +a` provides `GROWTHBOOK_ADMIN_PAT`):
   - repo: `gh api repos/ojones/<app>` returns 404 (deleted) or `archived: true` (archived)
   - Fly app: `curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(fly auth token)" https://api.machines.dev/v1/apps/<app>` returns 404 (403 means the name is held by another account and was never ours, which is fine)
   - SDK connection: no entry named `<app>` in `curl -s -H "Authorization: Bearer $GROWTHBOOK_ADMIN_PAT" https://ai-factory-growthbook.fly.dev:3100/api/v1/sdk-connections`
   - flags: every `<app>.` flag in `.../api/v1/features?limit=100` has `archived: true`
6. **Report** the verified result per resource. GrowthBook cannot delete flags, only archive them, so say that archived flags still exist in the project.
7. **Record it**: if there is a related open ticket (such as the cleanup ticket #40), comment which apps were removed.

## If the script fails

- *Repo delete fails with 403 or "Must have admin rights"*: the `FACTORY_PAT` lacks the fine-grained Administration permission. Tell the user; do not try another token.
- *The Fly app is "not in our account"*: it belongs to someone else. Leave it; the rest of the teardown still applies.
- *Flag archive fails*: the admin PAT may have lost permission. Report it; do not use another credential.
- *Partial failure*: every step is check-then-act, so rerun the same workflow. The repo is deleted last so its marker stays available for retries.

## Keeping this skill current

When the teardown gains a resource (a new secret store, a new always-on service per app), add it to `teardown.sh` and to the checks in step 5. Update this file in the same commit.
