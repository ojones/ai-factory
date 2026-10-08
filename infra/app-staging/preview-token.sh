#!/usr/bin/env bash
# Derives a Managed App's Preview Token: HMAC-SHA256(PREVIEW_MASTER_SECRET, app slug),
# hex-encoded. GitHub secrets are write-only, so nothing is stored per app — App
# Staging pushes this value into the app's repo, and the Build Run recomputes it
# with this same script.
#
# Usage: PREVIEW_MASTER_SECRET=... preview-token.sh <app-slug>
set -euo pipefail

: "${PREVIEW_MASTER_SECRET:?PREVIEW_MASTER_SECRET must be set}"
slug="${1:?usage: preview-token.sh <app-slug>}"

printf %s "$slug" | openssl dgst -sha256 -hmac "$PREVIEW_MASTER_SECRET" -r | cut -d' ' -f1
