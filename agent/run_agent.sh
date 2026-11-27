#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
cd agent
exec python3 agent.py "$@"
