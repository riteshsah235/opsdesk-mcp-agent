#!/bin/sh
# Checks the requirements for the default contained run and prints one clear line per problem.
GG=${GG:-$(command -v gg || echo "$(dirname "$0")/../gg")}
bad=0
chk() { if ! eval "$2" >/dev/null 2>&1; then echo "MISSING: $1"; bad=1; else echo "ok: $1"; fi; }
chk "python3" "command -v python3"
chk "unshare" "command -v unshare"
chk "ip (iproute2)" "command -v ip"
chk "unprivileged user namespaces (unshare -rn)" "unshare -rn true"
chk "gg executable at $GG (set GG=/path/to/gg)" "[ -x \"$GG\" ]"
[ -n "${GROQ_API_KEY:-}" ] || { [ -f "$(dirname "$0")/../.env" ] && grep -q '^GROQ_API_KEY=.' "$(dirname "$0")/../.env"; } && echo "ok: GROQ_API_KEY set" || { echo "MISSING: GROQ_API_KEY (needed for the real model, not for tests)"; }
exit $bad
