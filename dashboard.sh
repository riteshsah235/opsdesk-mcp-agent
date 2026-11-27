#!/bin/sh
# Local dashboard on http://127.0.0.1:8765 (this computer only). PORT=9000 sh dashboard.sh to change the port.
set -eu
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
exec python3 dashboard/server.py
