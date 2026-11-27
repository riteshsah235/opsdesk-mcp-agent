#!/bin/sh
# One-command demo of the four sample orders. Use --offline to run without a Groq key.
set -eu
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
exec python3 agent/demo.py "$@"
