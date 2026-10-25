#!/usr/bin/env bash
# Thin, idempotent provisioning for what fly.toml can't express (per
# ARCHITECTURE.md's IaC approach): make sure the Fly app exists before
# deploying to it.
#
# Requires FLY_API_TOKEN and FLY_APP_NAME (the repo name) in the environment;
# FLY_ORG defaults to "personal".
# It also makes sure the app has its one 1 GB volume named `data` (mounted at
# /data by fly.toml), in the region fly.toml names as primary_region.
set -euo pipefail

: "${FLY_APP_NAME:?FLY_APP_NAME must be set (the repo name)}"
ORG="${FLY_ORG:-personal}"

if flyctl apps list --json 2>/dev/null | jq -e --arg name "$FLY_APP_NAME" 'any(.[]; .Name == $name)' >/dev/null; then
  echo "Fly app '$FLY_APP_NAME' already exists — nothing to provision."
else
  echo "Creating Fly app '$FLY_APP_NAME' in org '$ORG'..."
  flyctl apps create "$FLY_APP_NAME" --org "$ORG"
fi

REGION="$(sed -n 's/^primary_region *= *"\([^"]*\)".*/\1/p' fly.toml)"
: "${REGION:?fly.toml must name primary_region}"

if flyctl volumes list --app "$FLY_APP_NAME" --json | jq -e 'any(.[]; .name == "data")' >/dev/null; then
  echo "Volume 'data' already exists — nothing to provision."
else
  echo "Creating volume 'data' (1 GB) in '$REGION'..."
  flyctl volumes create data --app "$FLY_APP_NAME" --region "$REGION" --size 1 --yes
fi
