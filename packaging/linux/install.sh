#!/bin/sh
# PRISM installer for Linux. Normally run by the PRISM-...-setup.run file,
# which unpacks the app next to this script first.
#
# As a normal user it installs for you only, no sudo needed:
#   ~/.local/opt/prism                       the app (PRISM executable + its files)
#   ~/.local/bin/prism                       command to start it
#   ~/.local/share/applications/prism.desktop, icon   app menu entry
# As root (sudo) it installs for everyone: /opt/prism, /usr/local/bin/prism,
# /usr/local/share/applications. Your browsing data and settings live in
# ~/.local/share/Synterra/PRISM and are kept across updates and uninstalls.
set -eu

usage() {
  cat <<'USAGE'
Usage: sh PRISM-<version>-linux-<arch>-setup.run [options]

  --prefix DIR    install the app into DIR (default ~/.local/opt/prism, or /opt/prism as root)
  --partner       partner edition (no terminal or password vault)
  --employee      employee edition (removes a partner deployment.json)
  --no-menu       don't add an app menu entry or the `prism` command
  -y, --yes       don't ask for confirmation
  --extract [DIR] only unpack the installer (setup.run option)
  -h, --help      show this help

Updating: run a newer installer the same way. The edition you chose is kept.
Uninstalling: run <install folder>/uninstall.sh (add --purge to also delete
your PRISM data and settings).
USAGE
}

SRC=$(cd "$(dirname "$0")" && pwd)
VERSION=unknown
PREFIX=""
EDITION=""
MENU=1
ASK=1
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION=$2; shift ;;
    --prefix) [ $# -ge 2 ] || { echo "--prefix needs a folder" >&2; exit 2; }; PREFIX=$2; shift ;;
    --prefix=*) PREFIX=${1#--prefix=} ;;
    --partner) EDITION=partner ;;
    --employee) EDITION=employee ;;
    --no-menu) MENU=0 ;;
    -y|--yes) ASK=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

if [ ! -x "$SRC/PRISM/PRISM" ]; then
  echo "The PRISM app isn't next to this script ($SRC/PRISM/PRISM)." >&2
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  SCOPE="all users"
  APPDIR=${PREFIX:-/opt/prism}
  BINDIR=/usr/local/bin
  SHARE=/usr/local/share
else
  SCOPE="you ($(id -un))"
  APPDIR=${PREFIX:-$HOME/.local/opt/prism}
  BINDIR=$HOME/.local/bin
  SHARE=${XDG_DATA_HOME:-$HOME/.local/share}
fi
case "$APPDIR" in /*) ;; *) APPDIR=$(pwd)/$APPDIR ;; esac
APPDIR=${APPDIR%/}
DESKTOP=$SHARE/applications/prism.desktop
ICON=$SHARE/icons/hicolor/256x256/apps/prism.png
LAUNCHER=$BINDIR/prism
MARKER=.prism-install

# Never replace a folder PRISM didn't create.
if [ -e "$APPDIR" ] && [ ! -f "$APPDIR/$MARKER" ] && [ -n "$(ls -A "$APPDIR" 2>/dev/null)" ]; then
  echo "$APPDIR exists and isn't a PRISM install. Choose another folder with --prefix." >&2
  exit 1
fi
UPGRADE=""
[ -f "$APPDIR/$MARKER" ] && UPGRADE=$(sed -n 's/^version=//p' "$APPDIR/$MARKER")

echo "PRISM $VERSION"
echo "  install for: $SCOPE"
echo "  app folder:  $APPDIR${UPGRADE:+   (replaces PRISM $UPGRADE)}"
[ "$MENU" = 1 ] && echo "  command:     $LAUNCHER" && echo "  app menu:    $DESKTOP"
[ -n "$EDITION" ] && echo "  edition:     $EDITION"
if [ "$ASK" = 1 ] && [ -t 0 ]; then
  printf "Install? [Y/n] "
  read -r answer || answer=n
  case "$answer" in ""|y|Y|yes|YES) ;; *) echo "Cancelled."; exit 1 ;; esac
fi

# Install into a fresh folder next to the old one, then swap, so a failed copy
# never leaves a half-updated PRISM behind.
PARENT=$(dirname "$APPDIR")
mkdir -p "$PARENT"
NEW="$APPDIR.new.$$"
rm -rf "$NEW"
cp -R "$SRC/PRISM" "$NEW"
if [ -f "$APPDIR/deployment.json" ] && [ "$EDITION" = "" ]; then
  cp "$APPDIR/deployment.json" "$NEW/deployment.json"       # keep the edition chosen before
fi
if [ "$EDITION" = partner ]; then
  printf '{"edition": "partner"}\n' > "$NEW/deployment.json"
fi
OLD=""
if [ -e "$APPDIR" ]; then
  OLD="$APPDIR.old.$$"
  mv "$APPDIR" "$OLD"
fi
mv "$NEW" "$APPDIR"
[ -n "$OLD" ] && rm -rf "$OLD"

if [ "$MENU" = 1 ]; then
  mkdir -p "$BINDIR" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
  ln -sfn "$APPDIR/PRISM" "$LAUNCHER"
  cp "$SRC/icon.png" "$ICON"
  cat > "$DESKTOP" <<DESKTOP_ENTRY
[Desktop Entry]
Type=Application
Name=PRISM
GenericName=Web Browser
Comment=Privacy-first research browser
Exec="$APPDIR/PRISM" %U
Icon=prism
Terminal=false
Categories=Network;WebBrowser;
MimeType=text/html;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;application/pdf;image/svg+xml;
StartupWMClass=prism
StartupNotify=true
Actions=UpdateBlocklists;

[Desktop Action UpdateBlocklists]
Name=Update blocklists
Exec="$APPDIR/PRISM" --update-blocklists
DESKTOP_ENTRY
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$(dirname "$DESKTOP")" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$SHARE/icons/hicolor" 2>/dev/null || true
fi

# Ubuntu 23.10+ and its relatives: Qt WebEngine's sandbox needs an AppArmor
# profile (see apparmor.sh). Root writes it; a user install says how.
HELPER=_internal/PyQt6/Qt6/libexec/QtWebEngineProcess
cp "$SRC/apparmor.sh" "$APPDIR/apparmor.sh"
APPARMOR=""
if sh "$APPDIR/apparmor.sh" needed; then
  if [ "$(id -u)" -eq 0 ] && command -v apparmor_parser >/dev/null 2>&1; then
    sh "$APPDIR/apparmor.sh" install "$APPDIR/PRISM" "$APPDIR/$HELPER" && APPARMOR=1
  else
    echo
    echo "This system only lets programs with an AppArmor profile use the browser sandbox."
    echo "Allow PRISM once (needs your password):"
    echo "  sudo sh '$APPDIR/apparmor.sh' install '$APPDIR/PRISM' '$APPDIR/$HELPER'"
  fi
fi

{
  echo "version=$VERSION"
  [ -n "$APPARMOR" ] && echo "apparmor=1"
  echo "installed=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "$MENU" = 1 ]; then
    echo "launcher=$LAUNCHER"
    echo "desktop=$DESKTOP"
    echo "icon=$ICON"
  fi
} > "$APPDIR/$MARKER"

cat > "$APPDIR/uninstall.sh" <<'UNINSTALL'
#!/bin/sh
# Remove PRISM. Your data and settings (~/.local/share/Synterra/PRISM) stay
# unless you add --purge (which deletes them for the user running this).
set -eu
APPDIR=$(cd "$(dirname "$0")" && pwd)
[ -f "$APPDIR/.prism-install" ] || { echo "$APPDIR isn't a PRISM install." >&2; exit 1; }
PURGE=0; ASK=1
for a in "$@"; do
  case "$a" in --purge) PURGE=1 ;; -y|--yes) ASK=0 ;; *) echo "Usage: uninstall.sh [--purge] [-y]" >&2; exit 2 ;; esac
done
DATA=${XDG_DATA_HOME:-$HOME/.local/share}/Synterra/PRISM
echo "Remove PRISM from $APPDIR$( [ "$PURGE" = 1 ] && echo " and delete $DATA" )?"
if [ "$ASK" = 1 ] && [ -t 0 ]; then
  printf "[y/N] "; read -r answer || answer=n
  case "$answer" in y|Y|yes|YES) ;; *) echo "Cancelled."; exit 1 ;; esac
fi
get() { sed -n "s/^$1=//p" "$APPDIR/.prism-install"; }
LAUNCHER=$(get launcher); DESKTOP=$(get desktop); ICON=$(get icon)
if [ -n "$LAUNCHER" ] && [ -L "$LAUNCHER" ] && [ "$(readlink "$LAUNCHER")" = "$APPDIR/PRISM" ]; then rm -f "$LAUNCHER"; fi
if [ -n "$DESKTOP" ] && [ -f "$DESKTOP" ] && grep -q "$APPDIR/PRISM" "$DESKTOP"; then rm -f "$DESKTOP"; fi
[ -n "$ICON" ] && rm -f "$ICON"
if [ -n "$DESKTOP" ]; then
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$(dirname "$DESKTOP")" 2>/dev/null || true
fi
if [ -f /etc/apparmor.d/prism ] && grep -q "$APPDIR/PRISM" /etc/apparmor.d/prism; then
  if [ "$(id -u)" -eq 0 ]; then sh "$APPDIR/apparmor.sh" remove
  else echo "Also remove PRISM's AppArmor profile: sudo rm /etc/apparmor.d/prism"; fi
fi
rm -rf "$APPDIR"
if [ "$PURGE" = 1 ] && [ -d "$DATA" ]; then rm -rf "$DATA"; echo "Deleted $DATA"; fi
echo "PRISM was removed."
UNINSTALL
chmod +x "$APPDIR/uninstall.sh"

echo
echo "PRISM $VERSION is installed."
if [ "$MENU" = 1 ]; then
  echo "Start it from your app menu, or run: prism"
  case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *) echo "  ($BINDIR isn't on your PATH yet: add it, or run $APPDIR/PRISM)" ;;
  esac
else
  echo "Run: $APPDIR/PRISM"
fi
echo "Uninstall: $APPDIR/uninstall.sh"
