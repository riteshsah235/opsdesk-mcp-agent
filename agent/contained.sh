#!/bin/sh
# Starts the Graftcode Gateway inside a private network namespace and then runs agent/relay.py
# (stdin/stdout) in the same namespace. The gateway binds 0.0.0.0 but only inside that namespace,
# so nothing on the host network can reach it. Needs Linux `unshare` and `ip`.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
GG=${GG:-$(command -v gg || echo "$ROOT/gg")}
export ROOT GG
exec unshare -rn sh -c '
  ip link set lo up
  D=$(mktemp -d); cd "$D"
  [ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
  "$GG" --modules "$ROOT/service/" --port 18080 --httpPort 18081 >"$D/gg.log" 2>&1 &
  P=$!; trap "kill $P 2>/dev/null; rm -rf $D" EXIT
  i=0; until python3 -c "import socket;socket.create_connection((\"127.0.0.1\",18081),1)" 2>/dev/null; do i=$((i+1)); [ $i -gt 40 ] && { echo gateway did not start >&2; exit 1; }; sleep 1; done
  python3 "$ROOT/agent/relay.py" http://127.0.0.1:18081/mcp'
