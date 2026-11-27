#!/bin/sh
# Checks the requirements for the default contained run. One line per check, with the fix for each problem.
GG=${GG:-$(command -v gg || echo "$(dirname "$0")/../gg")}
bad=0
chk() { # name, test command, fix hint
  if eval "$2" >/dev/null 2>&1; then echo "ok: $1"; else echo "MISSING: $1"; echo "  fix: $3"; bad=1; fi
}
if grep -qi microsoft /proc/version 2>/dev/null; then
  echo "note: WSL detected. This setup has not been verified on WSL by the maintainers; if a check below fails, stop."
  if ! grep -qi wsl2 /proc/version 2>/dev/null; then
    echo "  If 'wsl -l -v' in PowerShell shows VERSION 1, see https://learn.microsoft.com/en-us/windows/wsl/compare-versions (WSL 1 has no full Linux kernel)."
  fi
fi
chk "python3" "command -v python3" "sudo apt install -y python3"
chk "unshare" "command -v unshare" "sudo apt install -y util-linux"
chk "ip (iproute2)" "command -v ip" "sudo apt install -y iproute2"
chk "unprivileged user namespaces (unshare -rn)" "unshare -rn true" "your kernel or container blocks user namespaces. Do not start the gateway another way; see README"
chk "gg executable at $GG (set GG=/path/to/gg)" "[ -x \"$GG\" ]" "curl -fsSL grft.dev/get/gg | sh  (Debian/Ubuntu: then sudo dpkg -i gg.deb)"
[ -n "${GROQ_API_KEY:-}" ] || { [ -f "$(dirname "$0")/../.env" ] && grep -q '^GROQ_API_KEY=.' "$(dirname "$0")/../.env"; } && echo "ok: GROQ_API_KEY set" || echo "note: GROQ_API_KEY not set. Needed for the live model only. Use 'sh demo.sh --offline' without it."
exit $bad
