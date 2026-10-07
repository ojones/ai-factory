#!/usr/bin/env bash
# Thin, idempotent provisioning for what fly.toml can't express (per
# ARCHITECTURE.md's IaC approach): make sure the Fly app exists before
# deploying to it.
#
# Requires FLY_API_TOKEN and FLY_APP_NAME (the repo name) in the environment;
# FLY_ORG defaults to "personal".
set -euo pipefail

: "${FLY_APP_NAME:?FLY_APP_NAME must be set (the repo name)}"
ORG="${FLY_ORG:-personal}"

if flyctl apps list --json 2>/dev/null | jq -e --arg name "$FLY_APP_NAME" 'any(.[]; .Name == $name)' >/dev/null; then
  echo "Fly app '$FLY_APP_NAME' already exists — nothing to provision."
else
  echo "Creating Fly app '$FLY_APP_NAME' in org '$ORG'..."
  flyctl apps create "$FLY_APP_NAME" --org "$ORG"
fi
