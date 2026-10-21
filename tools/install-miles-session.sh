#!/bin/bash
# Installs the play-session levers (tools/miles-session) as root-owned copies and the sudo rule that
# lets the user run only that copy without a password:
#   sudo tools/install-miles-session.sh            install / update
#   sudo tools/install-miles-session.sh remove     uninstall
set -eu
here=$(cd "$(dirname "$0")" && pwd)
user=${SUDO_USER:?run through sudo}
rule=/etc/sudoers.d/miles-session
if [[ ${1:-} == remove ]]; then
    /usr/local/bin/miles-session stop 2>/dev/null || true
    rm -f "$rule" /usr/local/bin/miles-session
    rm -rf /usr/local/lib/miles-session
    echo "removed"
    exit 0
fi
install -D -o root -g root -m 755 "$here/miles-session" /usr/local/bin/miles-session
install -D -o root -g root -m 644 "$here/gpuclk.py" /usr/local/lib/miles-session/gpuclk.py
tmp=$(mktemp)
printf '%s ALL=(root) NOPASSWD: /usr/local/bin/miles-session start *, /usr/local/bin/miles-session stop\n' "$user" > "$tmp"
visudo -cqf "$tmp"
install -o root -g root -m 440 "$tmp" "$rule"
rm -f "$tmp"
echo "installed for $user"
