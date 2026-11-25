#!/usr/bin/env bash
# Set PRISM up to run from this checkout, on Linux or macOS.
#
#   ./setup.sh              install what's missing, then: .venv/bin/python prism.py
#   ./setup.sh --no-system  skip the system packages (you installed them yourself)
#   ./setup.sh -y           don't ask before using sudo
#
# Linux: finds the distro family in /etc/os-release and installs the
# libraries Qt WebEngine (Chromium) needs:
#   Debian, Ubuntu, Linux Mint, Pop!_OS, elementary, Zorin, Kali   apt
#   Fedora, RHEL, Rocky, AlmaLinux, CentOS Stream                  dnf
#   openSUSE Tumbleweed / Leap, SLES                               zypper
#   Arch, Manjaro, EndeavourOS, CachyOS                            pacman
# then makes .venv with the pinned Python packages (requirements.txt), the
# AppArmor profile Ubuntu 23.10+ needs for the browser sandbox, fresh
# blocklists, and an app menu entry.
# macOS: needs Python 3.10+ (python.org or Homebrew: brew install python).
#
# Windows: see README.md (Run).
set -euo pipefail
cd "$(dirname "$0")"

SYSTEM=1
ASK=1
for a in "$@"; do
  case "$a" in
    --no-system) SYSTEM=0 ;;
    -y|--yes) ASK=0 ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $a (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO=sudo
confirm() {
  [ "$ASK" = 0 ] && return 0
  [ -t 0 ] || return 0
  printf '%s [Y/n] ' "$1"
  read -r answer || answer=n
  case "$answer" in ""|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

OS=$(uname -s)
PY=""

# ---------------------------------------------------------------- system packages
if [ "$OS" = Darwin ]; then
  say "macOS $(sw_vers -productVersion) ($(uname -m))"
  major=$(sw_vers -productVersion | cut -d. -f1)
  if [ "$major" -lt 13 ]; then
    echo "PRISM's Qt WebEngine needs macOS 13 Ventura or later." >&2
    exit 1
  fi
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      PY=$c; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "Install Python 3.10 or newer first: https://www.python.org/downloads/macos/  (or: brew install python)" >&2
    exit 1
  fi
elif [ "$OS" = Linux ]; then
  ID="" ID_LIKE="" PRETTY_NAME="Linux"
  # shellcheck disable=SC1091
  [ -r /etc/os-release ] && . /etc/os-release
  FAMILY=""
  for id in $ID $ID_LIKE; do
    case "$id" in
      debian|ubuntu) FAMILY=apt; break ;;
      fedora|rhel|centos|rocky|almalinux) FAMILY=dnf; break ;;
      opensuse*|suse|sles) FAMILY=zypper; break ;;
      arch|archlinux) FAMILY=pacman; break ;;
    esac
  done
  say "$PRETTY_NAME ($(uname -m)), package manager: ${FAMILY:-unknown}"

  if [ "$SYSTEM" = 1 ]; then
    case "$FAMILY" in
      apt)
        pkgs="python3 python3-venv python3-pip libdbus-1-3 libdrm2 libegl1 libfontconfig1 libgbm1 libgl1
              libnspr4 libnss3 libx11-xcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
              libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1
              libxcomposite1 libxdamage1 libxkbcommon-x11-0 libxkbcommon0 libxkbfile1 libxrandr2
              libxshmfence1 libxtst6 libgssapi-krb5-2 libbrotli1 libpulse0 libcups2 libwayland-client0
              libwayland-cursor0 libwayland-egl1 libxfixes3 libxext6 ca-certificates fonts-dejavu-core"
        # Ubuntu 24.04+ / Debian 13+ renamed these ("t64").
        for p in libasound2t64:libasound2 libglib2.0-0t64:libglib2.0-0; do
          if apt-cache show "${p%%:*}" >/dev/null 2>&1; then pkgs="$pkgs ${p%%:*}"; else pkgs="$pkgs ${p#*:}"; fi
        done
        # shellcheck disable=SC2086
        confirm "Install the system packages with apt (sudo)?" && $SUDO apt-get update && $SUDO apt-get install -y $pkgs
        ;;
      dnf)
        pkgs="python3 python3-pip alsa-lib dbus-libs libdrm mesa-libEGL mesa-libgbm mesa-libGL fontconfig
              glib2 nspr nss libX11-xcb xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms
              xcb-util-renderutil libxcb libXcomposite libXdamage libxkbcommon libxkbcommon-x11 libxkbfile
              libXrandr libxshmfence libXtst krb5-libs libbrotli pulseaudio-libs cups-libs libwayland-client
              libwayland-cursor libwayland-egl libXfixes libXext ca-certificates dejavu-sans-mono-fonts"
        # shellcheck disable=SC2086
        confirm "Install the system packages with dnf (sudo)?" && $SUDO dnf install -y $pkgs
        ;;
      zypper)
        pkgs="python3 python3-pip alsa libdbus-1-3 libdrm2 libEGL1 fontconfig libgbm1 libGL1 libglib-2_0-0
              mozilla-nspr mozilla-nss libX11-xcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
              libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1
              libXcomposite1 libXdamage1 libxkbcommon-x11-0 libxkbcommon0 libxkbfile1 libXrandr2
              libxshmfence1 libXtst6 krb5 libbrotlidec1 libpulse0 libcups2 libwayland-client0
              libwayland-cursor0 libwayland-egl1 libXfixes3 libXext6 ca-certificates dejavu-fonts"
        # shellcheck disable=SC2086
        confirm "Install the system packages with zypper (sudo)?" && $SUDO zypper --non-interactive install $pkgs
        ;;
      pacman)
        # Arch's own Qt WebEngine gets Chromium fixes with pacman -Syu: prefer
        # the native package (packaging/arch/PKGBUILD) or SETUP_ARCH.md.
        echo "On Arch, the pacman package is the better way: see README.md (Arch Linux package)."
        echo "Continuing with a virtual environment (same pinned packages as Windows)."
        confirm "Install the system packages with pacman (sudo)?" && \
          $SUDO pacman -S --needed --noconfirm python nss alsa-lib libxkbcommon-x11 xcb-util-cursor \
            xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libxkbfile libxshmfence krb5 brotli \
            libpulse libcups wayland libxfixes libxext ca-certificates ttf-dejavu
        ;;
      *)
        echo "Unknown distro: install Python 3.10+, NSS, ALSA, libxkbcommon-x11 and the xcb-util libraries"
        echo "(see the Dockerfile for the full list), then run ./setup.sh --no-system."
        ;;
    esac
  fi
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      PY=$c; break
    fi
  done
  [ -n "$PY" ] || { echo "PRISM needs Python 3.10 or newer." >&2; exit 1; }
else
  echo "This script is for Linux and macOS. On Windows, see README.md (Run)." >&2
  exit 1
fi

# ---------------------------------------------------------------- Python packages
say "Virtual environment (.venv) with $($PY --version)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
.venv/bin/python -c "from PyQt6.QtWebEngineWidgets import QWebEngineView; import cryptography; print('    Qt WebEngine and cryptography import fine')"

# ---------------------------------------------------------------- sandbox (Ubuntu 23.10+)
if [ "$OS" = Linux ] && sh packaging/linux/apparmor.sh needed; then
  say "AppArmor profile for the browser sandbox"
  PYBIN=$(readlink -f .venv/bin/python)
  HELPER=$(.venv/bin/python -c 'import PyQt6, os; print(os.path.join(PyQt6.__path__[0], "Qt6", "libexec", "QtWebEngineProcess"))')
  echo "    This system lets only programs with an AppArmor profile use the browser sandbox."
  echo "    The profile covers $PYBIN and $HELPER."
  if confirm "Install it (sudo)?"; then
    $SUDO sh packaging/linux/apparmor.sh install "$PYBIN" "$HELPER"
  else
    echo "    Skipped: PRISM will stop with \"No usable sandbox\" until it's installed."
  fi
fi

# ---------------------------------------------------------------- blocklists
say "Blocklists (~260k ad/tracker + ~150k malware/phishing domains)"
.venv/bin/python update_blocklists.py || echo "    some lists failed; PRISM uses its built-in list until the next update"

# ---------------------------------------------------------------- launcher
if [ "$OS" = Linux ]; then
  say "App menu entry"
  apps=${XDG_DATA_HOME:-$HOME/.local/share}/applications
  icons=${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps
  mkdir -p "$apps" "$icons"
  cp assets/icon.png "$icons/prism.png"
  here=$(pwd)
  cat > "$apps/prism.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PRISM
GenericName=Web Browser
Comment=Privacy-first research browser
Exec="$here/.venv/bin/python" "$here/prism.py" %U
Path=$here
Icon=prism
Terminal=false
Categories=Network;WebBrowser;
MimeType=text/html;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;application/pdf;image/svg+xml;
StartupWMClass=prism
StartupNotify=true
EOF
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$apps" 2>/dev/null || true
  echo "    $apps/prism.desktop"
  echo "    Make PRISM your default browser:  xdg-settings set default-web-browser prism.desktop"
fi

say "Done. Start PRISM with:  .venv/bin/python prism.py"
[ "$OS" = Darwin ] && echo "    (an installable PRISM.app: packaging/build_macos.sh)"
exit 0
