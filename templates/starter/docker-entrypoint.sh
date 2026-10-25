#!/bin/sh
set -e
mkdir -p "$DATA_DIR"
chown node:node "$DATA_DIR"
exec su-exec node "$@"
