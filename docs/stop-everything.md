# Stopping everything by hand

There is no built-in factory-wide pause. Nothing runs continuously, so stopping means switching off what can start a run and cancelling what is in flight. This is the whole procedure; it uses only the GitHub CLI, and each command can be undone.

What bounds the damage if you are not watching: a run's cost cap ($2 default, $10 ceiling), the daily cap across runs (`limits.daily_cost_cap_usd`, $10), the provider-balance check (a run stops as `provider_blocked` when the account is empty), one run at a time per app, the retry limit, and flags that stay dark until a release passes.

## Stop

Disable every workflow that can start a Build Run or an Agent. The scheduled ones start runs on their own; the others start when a label is added:

```bash
for w in "Template sync" "Maintenance" "Production feedback" "Update Intake" "App Staging" \
         "Approve retirement of a dark feature" "Build Run" "Factory Run" "Benchmark"; do
  gh workflow disable "$w" -R ojones/ai-factory
done
```

Cancel what is running. A cancelled Build Run still writes its Report (the finalize step runs when cancelled), and a flag it had not released stays off:

```bash
gh run list -R ojones/ai-factory --status in_progress --json databaseId --jq '.[].databaseId' \
  | xargs -n1 gh run cancel -R ojones/ai-factory
```

To stop spending at the provider as well, turn off or rotate the DeepInfra key. To stop new runs while leaving the workflows on, set `limits.daily_cost_cap_usd` in `agents/profiles.yml` to a small positive number (0 means no cap), which refuses new runs for the day.

## Resume

```bash
for w in "Template sync" "Maintenance" "Production feedback" "Update Intake" "App Staging" \
         "Approve retirement of a dark feature" "Build Run" "Factory Run" "Benchmark"; do
  gh workflow enable "$w" -R ojones/ai-factory
done
```

A label added while a workflow was disabled is not replayed: for each Intake you still want, remove `proceed-with-change` and add it again. The scheduled workflows pick up where they left off at their next run.
