#!/bin/sh
# Starts the Graftcode Gateway on ./service. Reads .env if present.
# GC_PROJECT_KEY (optional) is read by gg from the environment, so it never appears on the command line.
set -eu
[ -f .env ] && set -a && . ./.env && set +a
GG=${GG:-./gg}
[ -x "$GG" ] || { echo "gg not found. Install it first, see README (curl -fsSL grft.dev/get/gg | sh)"; exit 1; }
exec "$GG" --modules ./service/ ${GG_ARGS:-}
