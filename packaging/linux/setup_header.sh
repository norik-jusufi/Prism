#!/bin/sh
# PRISM @VERSION@ installer for Linux (@ARCH@). Self-extracting: a shell
# script followed by a tar.gz of the app. Run it:  sh PRISM-...-setup.run
# Options are passed to install.sh: --help lists them.
set -eu
case "${1:-}" in
  --extract) DEST=${2:-PRISM-@VERSION@}; mkdir -p "$DEST" ;;
  *) DEST=$(mktemp -d "${TMPDIR:-/tmp}/prism-setup.XXXXXX"); trap 'rm -rf "$DEST"' EXIT INT TERM ;;
esac
if [ "$(uname -m)" != "@ARCH@" ]; then
  echo "This installer is for @ARCH@ Linux; this machine is $(uname -m)." >&2
  exit 1
fi
LINE=$(awk '/^__PRISM_ARCHIVE__$/ { print NR + 1; exit }' "$0")
tail -n +"$LINE" "$0" | tar -xzf - -C "$DEST"
if [ "${1:-}" = "--extract" ]; then
  echo "Extracted to $DEST (run $DEST/install.sh to install)"
  exit 0
fi
sh "$DEST/install.sh" --version "@VERSION@" "$@"
exit $?
__PRISM_ARCHIVE__
