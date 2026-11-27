#!/bin/sh
# Starts the Graftcode Gateway inside a private network namespace and then runs agent/relay.py
# (stdin/stdout) in the same namespace. The gateway binds 0.0.0.0 but only inside that namespace,
# so nothing on the host network can reach it. Needs Linux `unshare` and `ip`.
# Environment: the model key (GROQ_*) is removed before anything enters the namespace, and the
# gateway itself starts with a minimal environment: only GC_PROJECT_KEY (optional) is passed on.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
GG=${GG:-$(command -v gg || echo "$ROOT/gg")}
if [ -z "${GC_PROJECT_KEY:-}" ] && [ -f "$ROOT/.env" ]; then
  GC_PROJECT_KEY=$( . "$ROOT/.env" >/dev/null 2>&1; printf %s "${GC_PROJECT_KEY:-}" )
fi
export ROOT GG GC_PROJECT_KEY="${GC_PROJECT_KEY:-}"
exec env -u GROQ_API_KEY -u GROQ_MODEL unshare -rn sh -c '
  ip link set lo up
  D=$(mktemp -d); cd "$D"
  env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" LANG="${LANG:-C}" LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}" ${GC_PROJECT_KEY:+GC_PROJECT_KEY="$GC_PROJECT_KEY"} \
    "$GG" --modules "$ROOT/service/" --port 18080 --httpPort 18081 >"$D/gg.log" 2>&1 &
  P=$!; trap "kill $P 2>/dev/null; rm -rf $D" EXIT
  i=0; until python3 -c "import socket;socket.create_connection((\"127.0.0.1\",18081),1)" 2>/dev/null; do i=$((i+1)); [ $i -gt 40 ] && { echo gateway did not start >&2; exit 1; }; sleep 1; done
  python3 "$ROOT/agent/relay.py" http://127.0.0.1:18081/mcp'
