#!/bin/sh
# Runs the gateway AND the integration test inside a private Linux network namespace.
# gg binds 0.0.0.0, but inside the namespace that is a private loopback: nothing on the
# host network can reach it. Needs `unshare` and `ip` (Linux). No internet inside, so this
# runs test_agent.py only (no Groq call). Usage: GG=/path/to/gg ./test_isolated.sh
set -eu
GG=${GG:-$(command -v gg || echo ./gg)}
ROOT=$(pwd)
exec unshare -rn sh -c '
  ip link set lo up
  D=$(mktemp -d); cd "$D"
  "'"$GG"'" --modules "'"$ROOT"'/service/" --port 18080 --httpPort 18081 >gg.log 2>&1 &
  P=$!; sleep 12
  cd "'"$ROOT"'"; MCP_URL=http://127.0.0.1:18081/mcp python3 agent/test_agent.py; R=$?
  kill $P; rm -rf "$D"; exit $R'
