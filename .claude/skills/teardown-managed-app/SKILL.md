---
name: teardown-managed-app
description: Tear down a Managed App the Factory built (Fly app, GrowthBook SDK connection, GitHub repo). Use when the user wants a Managed App removed, retired or cleaned up, or asks what leftovers exist from failed or test Intakes.
---

# Tear down a Managed App

Removal is done by the `Teardown` workflow (`.github/workflows/teardown.yml`, script `infra/app-staging/teardown.sh`). Run it through `gh`; do not reimplement its steps by hand with `fly`, `gh repo delete` or `curl`. The script holds the safety checks (Intake marker on the repo, no Build Run in flight, Factory infrastructure refused). If it refuses, report why and stop.

The deletions are irreversible. The user must confirm each app by name in the current conversation, after seeing the dry-run plan. Never infer approval from an earlier teardown, and never batch several apps under one confirmation.

## Steps

1. **Pick the app.** If the user named one, use it. Otherwise list candidates: Managed App repos are the ones whose description starts with `Intake: ojones/ai-factory#`.
   ```bash
   gh repo list ojones --limit 200 --json name,description,isArchived \
     -q '.[] | select(.description | startswith("Intake: ojones/ai-factory#")) | "\(.name)\t\(.description)"'
   ```
   For each, say which Intake it came from and the outcome of its last Build Run (`gh run list --workflow build-run.yml`). Let the user choose. Do not suggest an app that has a Build Run in flight.
2. **Dry run.**
   ```bash
   gh workflow run teardown.yml -f app_name=<app> -f dry_run=true
   gh run watch "$(gh run list --workflow teardown.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
   gh run view --log "$(gh run list --workflow teardown.yml --limit 1 --json databaseId -q '.[0].databaseId')"
   ```
   Show the user the `[dry run] would:` lines and the flags listed for hand archiving.
3. **Ask for confirmation** naming the app and what will be destroyed. If the app is live and released, say so, since its users lose the service.
4. **Real run**, only after a yes: the same commands with `-f dry_run=false`.
5. **Verify**: the repo returns 404 (`gh api repos/ojones/<app>`), and the Fly app is gone (`curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(fly auth token)" https://api.machines.dev/v1/apps/<app>` returns 404).
6. **Hand over the flags.** GrowthBook's API cannot archive flags. Give the user the list from the run summary and the link https://ai-factory-growthbook.fly.dev/features. Say plainly that this part is still theirs to do.
7. **Record it**: if there is a related open ticket (such as the cleanup ticket #40), comment which apps were removed.

## If the script fails

- *Repo delete fails with 403 or "Must have admin rights"*: the `FACTORY_PAT` lacks the fine-grained Administration permission. Tell the user; do not try another token.
- *The Fly app is "not in our account"*: it belongs to someone else. Leave it; the rest of the teardown still applies.
- *Partial failure*: every step is check-then-act, so rerun the same workflow. The repo is deleted last so its marker stays available for retries.

## Keeping this skill current

When the teardown gains a resource (a new secret store, a new always-on service per app), add it to `teardown.sh` and to the checks in step 5. Update this file in the same commit.
