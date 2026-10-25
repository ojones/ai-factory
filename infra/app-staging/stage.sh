#!/usr/bin/env bash
# App Staging (ARCHITECTURE.md → Deployment provisioning; STEP 3.1, 3.2): stages one new Managed App from a planned `kind: staging` child ticket.
# Run by .github/workflows/app-staging.yml when `proceed-with-change` is added to such a child (the first child of a planned New App Intake).
#
# The app, its request and its cost cap come from the child and its parent Intake (orchestrator/staging/read_staging_child.py). After the seed push,
# orchestrator/staging/verify_infrastructure.py proves the app works; only then is the child closed, which starts the first business child.
#
# Every step is check-then-act, so re-adding `proceed-with-change` to the child after a partial failure is safe. Any non-success exit comments on the
# child and removes that label, since re-adding a label that is still present would not fire the workflow.
# STAGING_DRY_RUN=1 reads and checks the child, prints what it would stage and changes nothing.
#
# Env (see the workflow): GH_TOKEN (Actions token, for ai-factory issue ops), FACTORY_PAT, FLY_API_TOKEN, GROWTHBOOK_ADMIN_PAT, PREVIEW_MASTER_SECRET,
# ISSUE_NUMBER (the staging child), FACTORY_REPO, RUN_URL, RUNNER_TEMP, and for a failed check FACTORY_GH_TOKEN, DEEPINFRA_API_KEY and GITHUB_REPOSITORY.
set -euo pipefail
cd "$(dirname "$0")/../.."

GROWTHBOOK_API="${GROWTHBOOK_API_HOST:-https://ai-factory-growthbook.fly.dev:3100}/api/v1"
OWNER="${FACTORY_REPO%%/*}"

# --- helpers ----------------------------------------------------------------

# gh as the PAT: repo creation, secrets, seeding, and starting the next child.
pat() { GH_TOKEN="$FACTORY_PAT" "$@"; }

gb() { curl -sS --fail-with-body --max-time 30 \
  -H "Authorization: Bearer $GROWTHBOOK_ADMIN_PAT" -H 'Content-Type: application/json' "$@"; }

comment() { gh issue comment "$ISSUE_NUMBER" --repo "$FACTORY_REPO" --body "$1" >/dev/null; }
unlabel() { gh issue edit "$ISSUE_NUMBER" --repo "$FACTORY_REPO" --remove-label proceed-with-change >/dev/null || true; }

HANDLED=0
# Stop with an explanation on the child. Used for refusals and hard stops.
refuse() {
  HANDLED=1
  comment "**App Staging stopped:** $1

Fix this, then re-add the \`proceed-with-change\` label to try again. ([run]($RUN_URL))"
  echo "::error::$1"
  exit 1
}

on_exit() {
  local status=$?
  [ "$status" -eq 0 ] && return 0
  if [ "$HANDLED" != 1 ]; then
    comment "**App Staging failed** partway through. Every step is safe to repeat, so re-add the \`proceed-with-change\` label to retry. See the [run log]($RUN_URL)." || true
  fi
  unlabel
}
trap on_exit EXIT

# --- 1. read the staging child ----------------------------------------------------------

err="$(mktemp)"
child_out="$(PYTHONPATH=orchestrator python3 -m staging.read_staging_child 2>"$err")" || refuse "$(cat "$err")"
eval "$child_out"   # SLUG PARENT DESCRIPTION COST_CAP CAP_SOURCE, shell-quoted by the script
MARKER="Intake: ${FACTORY_REPO}#${PARENT}"
ISSUE_URL="https://github.com/${FACTORY_REPO}/issues/${PARENT}"
if [ -n "${STAGING_DRY_RUN:-}" ]; then
  HANDLED=1
  echo "dry run: would stage app $SLUG for Intake #$PARENT (child #$ISSUE_NUMBER), repo marker '$MARKER', cost cap \$$COST_CAP ($CAP_SOURCE)"
  exit 0
fi
gh label create "app:$SLUG" --repo "$FACTORY_REPO" --color 1d76db --description "Issues about the Managed App $SLUG" >/dev/null 2>&1 || true
gh issue edit "$PARENT" --repo "$FACTORY_REPO" --add-label "app:$SLUG" >/dev/null || true

# --- 3. the Fly app name: Fly app names are global across all of Fly -----------------
# 200 = ours (a rerun or a Managed App already deployed), 404 = free, 403 = taken by
# someone else. Checked here so a collision refuses at Intake, not mid-Build Run.

fly_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
  -H "Authorization: Bearer $FLY_API_TOKEN" "https://api.machines.dev/v1/apps/$SLUG")"
case "$fly_code" in
  200|404) ;;
  403) refuse "The Fly app name \`$SLUG\` is already taken by another Fly account (Fly app names are unique across all of Fly). Nothing was changed. Rename this issue to something more distinctive, such as \`$OWNER-$SLUG\`." ;;
  *) echo "::error::Unexpected HTTP $fly_code checking Fly app name $SLUG" >&2; exit 1 ;;
esac

# --- 4. the repo: create, or adopt only if the marker proves it is ours -----------

if out="$(pat gh api "repos/$OWNER/$SLUG" 2>&1)"; then
  existing="$(jq -r '.description // ""' <<<"$out")"
  [ "$existing" = "$MARKER" ] ||
    refuse "\`$OWNER/$SLUG\` already exists and was not created by this Intake (its description is not \`$MARKER\`). Nothing was changed. Rename this issue to use a different app name."
  echo "Repo $OWNER/$SLUG exists with our marker — adopting."
elif grep -q 'HTTP 404' <<<"$out"; then
  echo "Creating public repo $OWNER/$SLUG"
  pat gh api -X POST user/repos -f name="$SLUG" -f description="$MARKER" -F private=false >/dev/null
else
  echo "$out" >&2
  exit 1
fi

# GitHub's own free secret scanning, with push protection, so a known token pattern is blocked on push. Idempotent; a repo that cannot take
# the setting is warned about, not failed, because the Orchestrator also scans every coder diff before it pushes.
echo '{"security_and_analysis":{"secret_scanning":{"status":"enabled"},"secret_scanning_push_protection":{"status":"enabled"}}}' |
  pat gh api -X PATCH "repos/$OWNER/$SLUG" --input - >/dev/null 2>&1 ||
  echo "::warning::could not enable secret scanning with push protection on $OWNER/$SLUG"

# --- 5. GrowthBook: fresh app-scoped SDK key -----------------------------------------

project_json="$(gb "$GROWTHBOOK_API/projects?limit=100")"
[ "$(jq '.total' <<<"$project_json")" = 1 ] ||
  { echo "::error::Expected exactly one shared GrowthBook project." >&2; exit 1; }
PROJECT_ID="$(jq -r '.projects[0].id' <<<"$project_json")"

# Revoke any key already named for this app (a rerun), then mint a fresh one.
for id in $(gb "$GROWTHBOOK_API/sdk-connections?limit=100" | jq -r --arg n "$SLUG" '.connections[] | select(.name == $n) | .id'); do
  echo "Revoking existing SDK connection $id"
  gb -X DELETE "$GROWTHBOOK_API/sdk-connections/$id" >/dev/null
done
GROWTHBOOK_CLIENT_KEY="$(gb -X POST "$GROWTHBOOK_API/sdk-connections" \
  -d "$(jq -n --arg n "$SLUG" --arg p "$PROJECT_ID" '{name: $n, language: "nodejs", environment: "production", projects: [$p]}')" |
  jq -r '.sdkConnection.key')"
echo "::add-mask::$GROWTHBOOK_CLIENT_KEY"

# --- 6. secrets (before the seed push, whose Test Gate → Build → Deploy chain needs them)

PREVIEW_TOKEN="$(infra/app-staging/preview-token.sh "$SLUG")"
echo "::add-mask::$PREVIEW_TOKEN"

push_secret() { printf %s "$2" | pat gh secret set "$1" --repo "$OWNER/$SLUG" >/dev/null; echo "Set secret $1"; }
push_secret FLY_API_TOKEN "$FLY_API_TOKEN"
push_secret GROWTHBOOK_CLIENT_KEY "$GROWTHBOOK_CLIENT_KEY"
push_secret PREVIEW_TOKEN "$PREVIEW_TOKEN"

# --- 7. seed: tracked Starter Template files + INTAKE.md, one commit ------------------

AUTH_HEADER="Authorization: Basic $(printf 'x-access-token:%s' "$FACTORY_PAT" | base64 | tr -d '\n')"
echo "::add-mask::${AUTH_HEADER#Authorization: Basic }"
REMOTE="https://github.com/$OWNER/$SLUG.git"
pgit() { git -c "http.extraheader=$AUTH_HEADER" "$@"; }

if pgit ls-remote --exit-code --heads "$REMOTE" main >/dev/null 2>&1; then
  echo "Repo already seeded — skipping."
else
  work="$(mktemp -d)"
  git archive --format=tar HEAD:templates/starter | tar -x -C "$work"
  git rev-parse HEAD >"$work/.factory-template"  # the ai-factory commit these template files came from (template_sync.py)
  {
    echo "# Intake"
    echo
    echo "Source: $ISSUE_URL"
    echo "Cost cap: \$$COST_CAP ($CAP_SOURCE)"
    echo
    echo "## Spec"
    echo
    printf '%s\n' "$DESCRIPTION"
  } >"$work/INTAKE.md"
  git -C "$work" init -q -b main
  git -C "$work" add -A
  git -C "$work" -c user.name=ai-factory -c user.email=ai-factory@users.noreply.github.com \
    commit -q -m "Seed from Starter Template for Intake #$PARENT"
  pgit -C "$work" push -q "$REMOTE" main
  echo "Seeded $OWNER/$SLUG"
fi

# A failed check is a failure event: the Retrospective judges it and Try Fix files the fix, so the failure heals through the same loop as a failed Build Run.
EVENTS="$RUNNER_TEMP/staging-events.json"
VERDICTS="$RUNNER_TEMP/staging-verdicts.json"
hand_failures_to_try_fix() {
  PYTHONPATH=orchestrator python3 -m retrospective.judge_events "$EVENTS" "$VERDICTS" &&
    PYTHONPATH=orchestrator python3 -m try_fix.file_events "$VERDICTS" ||
    comment "**The failed checks could not be handed to Try Fix**, so no fix was filed. See the [run log]($RUN_URL)."
}

# --- 8. verify, then hand on ------------------------------------------------------------
# Prove the seeded app works, tell the Intake, and close the child so the first business child starts.

SEED_SHA="$(pgit ls-remote "$REMOTE" refs/heads/main | cut -f1)"
if ! APP_NAME="$SLUG" SEED_SHA="$SEED_SHA" FAILURE_EVENTS_FILE="$EVENTS" PYTHONPATH=orchestrator python3 -m staging.verify_infrastructure; then
  HANDLED=1
  hand_failures_to_try_fix
  exit 1   # verify_infrastructure commented the failed checks on the child; on_exit takes the start label off so adding it again retries
fi
gh issue comment "$PARENT" --repo "$FACTORY_REPO" --body "**App Staging complete.** Managed App repo: https://github.com/$OWNER/$SLUG

Cost cap for its Build Runs: \$$COST_CAP ($CAP_SOURCE). The app is built, deployed and verified; its first change set starts next. ([run]($RUN_URL))" >/dev/null
FACTORY_PAT="$FACTORY_PAT" PYTHONPATH=orchestrator python3 -m retrospective.close_child close "$FACTORY_REPO" "$ISSUE_NUMBER"
