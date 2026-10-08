#!/usr/bin/env bash
# Teardown of one Managed App (issue #40). Run by .github/workflows/teardown.yml.
#
# Deletes what App Staging and the first Build Run created: the Fly app, the
# GrowthBook SDK connection, and the GitHub repo. GrowthBook's REST API cannot
# delete or archive flags, so those are listed for archiving by hand in the UI.
#
# Dry run (the default) prints the plan and changes nothing. A repo is only
# touched if its description carries our Intake marker, so this can never
# delete a repo App Staging did not create.
#
# Env: FACTORY_PAT (needs delete_repo), FLY_API_TOKEN, GROWTHBOOK_ADMIN_PAT,
# FACTORY_REPO, APP_NAME, DRY_RUN (true|false).
set -euo pipefail

GROWTHBOOK_API="${GROWTHBOOK_API_HOST:-https://ai-factory-growthbook.fly.dev:3100}/api/v1"
OWNER="${FACTORY_REPO%%/*}"
SLUG="$APP_NAME"
DRY_RUN="${DRY_RUN:-true}"

pat() { GH_TOKEN="$FACTORY_PAT" "$@"; }
gb() { curl -sS --fail-with-body --max-time 30 -H "Authorization: Bearer $GROWTHBOOK_ADMIN_PAT" "$@"; }
fly_api() { curl -sS --max-time 30 -H "Authorization: Bearer $FLY_API_TOKEN" "$@"; }
act() { # act "description" cmd...: run it, or just announce it on a dry run
  local what="$1"; shift
  if [ "$DRY_RUN" = true ]; then echo "[dry run] would: $what"; else echo "$what"; "$@"; fi
}

[[ "$SLUG" =~ ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ && ${#SLUG} -le 30 ]] ||
  { echo "::error::'$SLUG' is not a valid Managed App name." >&2; exit 1; }
case "$SLUG" in ai-factory|ai-factory-growthbook)
  echo "::error::'$SLUG' is Factory infrastructure, not a Managed App." >&2; exit 1 ;;
esac

echo "Teardown of '$SLUG' (dry run: $DRY_RUN)"

# --- the repo must be ours, and no Build Run may be using the app -------------------
repo_desc=""
if out="$(pat gh api "repos/$OWNER/$SLUG" 2>&1)"; then
  repo_desc="$(jq -r '.description // ""' <<<"$out")"
  [[ "$repo_desc" == "Intake: ${FACTORY_REPO}#"* ]] ||
    { echo "::error::$OWNER/$SLUG exists but was not created by App Staging (description: '$repo_desc'). Refusing." >&2; exit 1; }
  REPO_EXISTS=true
elif grep -q 'HTTP 404' <<<"$out"; then
  REPO_EXISTS=false; echo "Repo $OWNER/$SLUG: already gone."
else
  echo "$out" >&2; exit 1
fi

for status in queued in_progress; do
  running="$(gh run list --repo "$FACTORY_REPO" --workflow build-run.yml --status "$status" --json url --jq '.[0].url // empty')"
  [ -z "$running" ] || { echo "::error::A Build Run is in flight ($running). Wait for it to finish." >&2; exit 1; }
done

# --- Fly app --------------------------------------------------------------------------
fly_code="$(fly_api -o /dev/null -w '%{http_code}' "https://api.machines.dev/v1/apps/$SLUG")"
case "$fly_code" in
  200) act "destroy Fly app $SLUG" fly_api -f -X DELETE "https://api.machines.dev/v1/apps/$SLUG" ;;
  404) echo "Fly app $SLUG: already gone." ;;
  403) echo "Fly app $SLUG: not in our account, leaving it alone." ;;
  *) echo "::error::Unexpected HTTP $fly_code for Fly app $SLUG" >&2; exit 1 ;;
esac

# --- GrowthBook: the SDK connection; list the flags for hand archiving ---------------
for id in $(gb "$GROWTHBOOK_API/sdk-connections?limit=100" | jq -r --arg n "$SLUG" '.connections[] | select(.name == $n) | .id'); do
  act "revoke GrowthBook SDK connection $id" gb -o /dev/null -X DELETE "$GROWTHBOOK_API/sdk-connections/$id"
done
flags="$(gb "$GROWTHBOOK_API/features?limit=100" | jq -r --arg p "$SLUG." '.features[] | select((.id | startswith($p)) and (.archived | not)) | .id')"
if [ -n "$flags" ]; then
  echo "GrowthBook flags to archive by hand (the REST API cannot do it): https://ai-factory-growthbook.fly.dev/features"
  sed 's/^/  - /' <<<"$flags"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    { echo "### Archive these GrowthBook flags by hand"; sed 's/^/- `/; s/$/`/' <<<"$flags"; } >>"$GITHUB_STEP_SUMMARY"
  fi
fi

# --- the repo, last, so a failed earlier step can be retried with the marker intact ---
[ "$REPO_EXISTS" = false ] || act "delete repo $OWNER/$SLUG" pat gh api -X DELETE "repos/$OWNER/$SLUG"
