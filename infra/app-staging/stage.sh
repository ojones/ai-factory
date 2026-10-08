#!/usr/bin/env bash
# App Staging (ARCHITECTURE.md → Deployment provisioning): stages one new
# Managed App from an Intake issue. Run by .github/workflows/app-staging.yml.
#
# Every step is check-then-act, so re-adding the `ready-for-staging` label
# after a partial failure is safe. Any non-success exit comments on the Intake
# issue and removes that label, since re-adding a label that is still present
# would not fire the workflow.
#
# Env (see the workflow): GH_TOKEN (Actions token, for ai-factory issue ops),
# FACTORY_PAT, FLY_API_TOKEN, GROWTHBOOK_ADMIN_PAT, PREVIEW_MASTER_SECRET,
# ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY, FACTORY_REPO, RUN_URL.
set -euo pipefail
cd "$(dirname "$0")/../.."

GROWTHBOOK_API="${GROWTHBOOK_API_HOST:-https://ai-factory-growthbook.fly.dev:3100}/api/v1"
OWNER="${FACTORY_REPO%%/*}"
SLUG="$(printf %s "$ISSUE_TITLE" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
MARKER="Intake: ${FACTORY_REPO}#${ISSUE_NUMBER}"
ISSUE_URL="https://github.com/${FACTORY_REPO}/issues/${ISSUE_NUMBER}"

# --- helpers ----------------------------------------------------------------

# gh as the PAT: repo creation, secrets, seeding, and the Build Run dispatch.
pat() { GH_TOKEN="$FACTORY_PAT" "$@"; }

gb() { curl -sS --fail-with-body --max-time 30 \
  -H "Authorization: Bearer $GROWTHBOOK_ADMIN_PAT" -H 'Content-Type: application/json' "$@"; }

comment() { gh issue comment "$ISSUE_NUMBER" --repo "$FACTORY_REPO" --body "$1" >/dev/null; }
unlabel() { gh issue edit "$ISSUE_NUMBER" --repo "$FACTORY_REPO" --remove-label ready-for-staging >/dev/null || true; }

HANDLED=0
# Stop with an explanation on the issue. Used for refusals and hard stops.
refuse() {
  HANDLED=1
  comment "**App Staging stopped:** $1

Fix this, then re-add the \`ready-for-staging\` label to try again. ([run]($RUN_URL))"
  echo "::error::$1"
  exit 1
}

on_exit() {
  local status=$?
  [ "$status" -eq 0 ] && return 0
  if [ "$HANDLED" != 1 ]; then
    comment "**App Staging failed** partway through. Every step is safe to repeat, so re-add the \`ready-for-staging\` label to retry. See the [run log]($RUN_URL)." || true
  fi
  unlabel
}
trap on_exit EXIT

# Text under "### <heading>" in an Issue Form body, surrounding blanks trimmed.
section() {
  printf %s "$ISSUE_BODY" | tr -d '\r' | awk -v h="### $1" '
    $0 == h { on = 1; next }
    /^### / { on = 0 }
    on { lines[++n] = $0 }
    END {
      s = 1; while (s <= n && lines[s] == "") s++
      e = n; while (e >= s && lines[e] == "") e--
      for (i = s; i <= e; i++) print lines[i]
    }'
}

# --- 1. validate the Intake ---------------------------------------------------

[[ "$SLUG" =~ ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ && ${#SLUG} -le 30 ]] ||
  refuse "The issue title \`$SLUG\` is not a valid Managed App name. Use lowercase letters, digits and single hyphens, starting with a letter, at most 30 characters (e.g. \`recipe-box\`)."

DESCRIPTION="$(section 'What should be built?')"
{ [ -n "$DESCRIPTION" ] && [ "$DESCRIPTION" != "_No response_" ]; } ||
  refuse "The \"What should be built?\" field is empty."

DEFAULT_CAP="$(sed -n 's/^ *cost_cap_usd_default: *//p' agents/profiles.yml)"
CEILING="$(sed -n 's/^ *cost_cap_usd_ceiling: *//p' agents/profiles.yml)"
CAP_INPUT="$(section 'Cost cap override (USD)' | sed 's/^\$//')"
if [ -z "$CAP_INPUT" ] || [ "$CAP_INPUT" = "_No response_" ]; then
  COST_CAP="$DEFAULT_CAP"; CAP_SOURCE="default"
else
  [[ "$CAP_INPUT" =~ ^[0-9]+(\.[0-9]+)?$ ]] ||
    refuse "The cost cap override \`$CAP_INPUT\` is not a number of dollars."
  awk -v c="$CAP_INPUT" -v m="$CEILING" 'BEGIN { exit !(c > 0 && c <= m) }' ||
    refuse "The cost cap override \$$CAP_INPUT must be greater than 0 and at most the \$$CEILING ceiling."
  COST_CAP="$CAP_INPUT"; CAP_SOURCE="override"
fi

# --- 2. one Managed App at a time ----------------------------------------------

others="$(gh issue list --repo "$FACTORY_REPO" --state open --label intake --label ready-for-staging \
  --json number --jq "[.[].number | select(. != $ISSUE_NUMBER)] | map(\"#\\(.)\") | join(\", \")")"
[ -z "$others" ] || refuse "Intake issue(s) $others are already past \`ready-for-staging\`. v1 runs one Managed App through Intake → App Staging → Build Run at a time."

for status in queued in_progress; do
  running="$(gh run list --repo "$FACTORY_REPO" --workflow build-run.yml --status "$status" --json url --jq '.[0].url // empty')"
  [ -z "$running" ] || refuse "A Build Run is in flight ($running). v1 runs one Managed App at a time."
done

# --- 3. the repo: create, or adopt only if the marker proves it is ours -----------

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

# --- 4. GrowthBook: fresh app-scoped SDK key, and the kill switch -------------------

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

# The kill switch fails closed, so it must exist and be on or the app only ever
# serves its maintenance response. Never touch an existing one: an owner's
# manual "off" must stick.
KILL_KEY="$SLUG.global-kill-switch"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
  -H "Authorization: Bearer $GROWTHBOOK_ADMIN_PAT" "$GROWTHBOOK_API/features/$KILL_KEY")"
if [ "$code" = 200 ]; then
  echo "Kill switch $KILL_KEY exists — leaving it alone."
else
  echo "Creating kill switch $KILL_KEY (on)"
  gb -X POST "$GROWTHBOOK_API/features" -d "$(jq -n --arg id "$KILL_KEY" --arg p "$PROJECT_ID" '{
    id: $id, owner: "ai-factory", valueType: "boolean", defaultValue: "true", project: $p,
    environments: {production: {enabled: true, rules: []}}}')" >/dev/null
fi

# --- 5. secrets (before the seed push, whose Test Gate → Build → Deploy chain needs them)

PREVIEW_TOKEN="$(infra/app-staging/preview-token.sh "$SLUG")"
echo "::add-mask::$PREVIEW_TOKEN"

push_secret() { printf %s "$2" | pat gh secret set "$1" --repo "$OWNER/$SLUG" >/dev/null; echo "Set secret $1"; }
push_secret FLY_API_TOKEN "$FLY_API_TOKEN"
push_secret GROWTHBOOK_CLIENT_KEY "$GROWTHBOOK_CLIENT_KEY"
push_secret PREVIEW_TOKEN "$PREVIEW_TOKEN"

# --- 6. seed: tracked Starter Template files + INTAKE.md, one commit ------------------

AUTH_HEADER="Authorization: Basic $(printf 'x-access-token:%s' "$FACTORY_PAT" | base64 | tr -d '\n')"
echo "::add-mask::${AUTH_HEADER#Authorization: Basic }"
REMOTE="https://github.com/$OWNER/$SLUG.git"
pgit() { git -c "http.extraheader=$AUTH_HEADER" "$@"; }

if pgit ls-remote --exit-code --heads "$REMOTE" main >/dev/null 2>&1; then
  echo "Repo already seeded — skipping."
else
  work="$(mktemp -d)"
  git archive --format=tar HEAD:templates/starter | tar -x -C "$work"
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
    commit -q -m "Seed from Starter Template for Intake #$ISSUE_NUMBER"
  pgit -C "$work" push -q "$REMOTE" main
  echo "Seeded $OWNER/$SLUG"
fi

# --- 7. hand off: dispatch the Build Run, then close the Intake -----------------------

pat gh workflow run build-run.yml --repo "$FACTORY_REPO" \
  -f issue_number="$ISSUE_NUMBER" -f app_name="$SLUG"

comment "**App Staging complete.** Managed App repo: https://github.com/$OWNER/$SLUG

Cost cap for its first Build Run: \$$COST_CAP ($CAP_SOURCE). The Build Run has been dispatched. ([run]($RUN_URL))"
gh issue close "$ISSUE_NUMBER" --repo "$FACTORY_REPO" --reason completed >/dev/null
