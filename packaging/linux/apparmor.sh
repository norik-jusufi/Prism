#!/bin/sh
# Ubuntu 23.10+ (and distros based on it: Mint 22, Pop!_OS 24.04, Zorin 18,
# elementary 8, ...) let only programs with an AppArmor profile create user
# namespaces. Chromium's sandbox, and so Qt WebEngine's, needs them: without
# a profile PRISM stops with "No usable sandbox". This installs a profile
# that allows exactly that for PRISM's two programs, like the one Google
# Chrome ships, and changes nothing else.
#
#   sh apparmor.sh needed                    exit 0 if this machine needs it
#   sudo sh apparmor.sh install APP HELPER   write /etc/apparmor.d/prism and load it
#   sudo sh apparmor.sh remove               delete and unload it
#
# APP is PRISM's executable (the built PRISM, or the venv's python for a
# source checkout), HELPER is Qt WebEngine's QtWebEngineProcess.
set -eu

PROFILE=/etc/apparmor.d/prism
RESTRICT=/proc/sys/kernel/apparmor_restrict_unprivileged_userns

needed() {
  [ -r "$RESTRICT" ] && [ "$(cat "$RESTRICT")" = 1 ]
}

case "${1:-}" in
  needed)
    needed
    ;;
  install)
    [ $# -eq 3 ] || { echo "usage: apparmor.sh install APP HELPER" >&2; exit 2; }
    needed || { echo "AppArmor doesn't restrict user namespaces here: nothing to do."; exit 0; }
    app=$(readlink -f "$2"); helper=$(readlink -f "$3")
    case "$app$helper" in *'"'*) echo "Paths with quotes aren't supported." >&2; exit 1 ;; esac
    cat > "$PROFILE" <<EOF
# PRISM: let its browser engine create the user namespaces Chromium's
# sandbox needs (written by PRISM's installer; remove with apparmor.sh remove).
abi <abi/4.0>,
include <tunables/global>

profile prism "$app" flags=(unconfined) {
  userns,
  include if exists <local/prism>
}

profile prism-webengine "$helper" flags=(unconfined) {
  userns,
  include if exists <local/prism-webengine>
}
EOF
    apparmor_parser -r "$PROFILE"
    echo "AppArmor profile installed: $PROFILE"
    ;;
  remove)
    if [ -f "$PROFILE" ]; then
      apparmor_parser -R "$PROFILE" 2>/dev/null || true
      rm -f "$PROFILE"
    fi
    ;;
  *)
    echo "usage: apparmor.sh needed | install APP HELPER | remove" >&2
    exit 2
    ;;
esac
