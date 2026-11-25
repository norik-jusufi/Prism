#!/usr/bin/env bash
# Turn the built app (dist/PRISM/) into distro packages:
#   dist/prism_<version>-1_<arch>.deb      Debian, Ubuntu, Linux Mint, Pop!_OS, elementary, Zorin, ...
#   dist/prism-<version>-<release>.<arch>.rpm  Fedora, RHEL / Rocky / Alma, openSUSE
# Both install the same thing: the app in /opt/prism, the `prism` command,
# an app menu entry registered as a web browser, and (on Ubuntu-style
# systems) the AppArmor profile Qt WebEngine's sandbox needs.
# Arch Linux has its own native package: packaging/arch/PKGBUILD.
#
# Called by build_linux.sh. Alone:  packaging/linux/make_packages.sh [deb] [rpm]
# (default: both; the .rpm needs rpmbuild: dnf install rpm-build, apt install rpm,
# pacman -S rpm-tools).
set -euo pipefail
cd "$(dirname "$0")/../.."

APP=dist/PRISM
[ -x "$APP/PRISM" ] || { echo "Build the app first (packaging/build_linux.sh): $APP/PRISM is missing." >&2; exit 1; }
FORMATS=${*:-deb rpm}
VERSION=$(sed -n 's/^VERSION *= *"\(.*\)"/\1/p' version.py)
ARCH=$(uname -m)
HELPER=_internal/PyQt6/Qt6/libexec/QtWebEngineProcess
SUMMARY="Privacy-first research browser"
DESCRIPTION="PRISM blocks ads, trackers, malware and phishing, keeps logins apart in
containers, sends DNS encrypted and has a full developer toolkit built in."

# The libraries the bundled Qt WebEngine needs from the system (everything
# else ships inside /opt/prism). Same list as the Dockerfile, which is tested
# in CI. Ubuntu 24.04+ renamed some with a "t64" suffix, hence the "|"s.
DEB_DEPENDS="libasound2t64 | libasound2, libdbus-1-3, libdrm2, libegl1, libfontconfig1, libgbm1, libgl1,
 libglib2.0-0t64 | libglib2.0-0, libnspr4, libnss3, libx11-xcb1, libxcb-cursor0, libxcb-icccm4,
 libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xfixes0,
 libxcb-xinerama0, libxcb-xkb1, libxcomposite1, libxdamage1, libxkbcommon-x11-0, libxkbcommon0,
 libxkbfile1, libxrandr2, libxshmfence1, libxtst6"
# RPM: by library name, which Fedora, RHEL and openSUSE all provide whatever
# they call the package.
RPM_REQUIRES=(libasound.so.2 libdbus-1.so.3 libdrm.so.2 libEGL.so.1 libfontconfig.so.1 libgbm.so.1 libGL.so.1
  libglib-2.0.so.0 libnspr4.so libnss3.so libX11-xcb.so.1 libxcb-cursor.so.0 libxcb-icccm.so.4
  libxcb-image.so.0 libxcb-keysyms.so.1 libxcb-randr.so.0 libxcb-render-util.so.0 libxcb-shape.so.0
  libxcb-xfixes.so.0 libxcb-xinerama.so.0 libxcb-xkb.so.1 libXcomposite.so.1 libXdamage.so.1
  libxkbcommon-x11.so.0 libxkbcommon.so.0 libxkbfile.so.1 libXrandr.so.2 libxshmfence.so.1 libXtst.so.6)

# --- the installed tree, shared by both formats
stage_root() {  # $1: folder to fill
  local root=$1
  mkdir -p "$root/opt" "$root/usr/bin" "$root/usr/share/applications" \
           "$root/usr/share/icons/hicolor/256x256/apps" "$root/usr/share/prism"
  cp -a "$APP" "$root/opt/prism"
  ln -s /opt/prism/PRISM "$root/usr/bin/prism"
  cp packaging/arch/prism.desktop "$root/usr/share/applications/prism.desktop"
  cp assets/icon.png "$root/usr/share/icons/hicolor/256x256/apps/prism.png"
  cp packaging/linux/apparmor.sh "$root/usr/share/prism/apparmor.sh"
  chmod 755 "$root/usr/share/prism/apparmor.sh"
}

POSTINST='#!/bin/sh
set -e
if sh /usr/share/prism/apparmor.sh needed && command -v apparmor_parser >/dev/null 2>&1; then
  sh /usr/share/prism/apparmor.sh install /opt/prism/PRISM /opt/prism/'"$HELPER"' || true
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
'
PRERM_REMOVE='sh /usr/share/prism/apparmor.sh remove || true'

# --- .deb
make_deb() {
  local darch
  case "$ARCH" in x86_64) darch=amd64 ;; aarch64) darch=arm64 ;; *) darch=$ARCH ;; esac
  # Debian versions: "1.2.0-beta" must sort before "1.2.0", which "~" does.
  local dver="${VERSION//-/\~}-1"
  local work=build/deb root out
  root=$work/root
  out="dist/prism_${dver}_${darch}.deb"
  rm -rf "$work"; mkdir -p "$root/DEBIAN"
  stage_root "$root"
  cat > "$root/DEBIAN/control" <<EOF
Package: prism
Version: $dver
Architecture: $darch
Maintainer: Synterra <noreply@synterra.invalid>
Installed-Size: $(du -sk "$root" | cut -f1)
Depends: $DEB_DEPENDS
Provides: www-browser
Section: web
Priority: optional
Homepage: https://github.com/norik-jusufi/Prism
Description: $SUMMARY
$(echo "$DESCRIPTION" | sed 's/^/ /')
EOF
  printf '%s' "$POSTINST" > "$root/DEBIAN/postinst"
  printf '#!/bin/sh\nset -e\nif [ "$1" = remove ] || [ "$1" = purge ]; then %s; fi\nexit 0\n' "$PRERM_REMOVE" > "$root/DEBIAN/prerm"
  chmod 755 "$root/DEBIAN/postinst" "$root/DEBIAN/prerm"
  if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --root-owner-group -Zxz --build "$root" "$out" >/dev/null
  else
    # No dpkg (e.g. building on Arch or Fedora): a .deb is just an ar archive.
    command -v ar >/dev/null 2>&1 || { echo "    skipped .deb: needs dpkg-deb or ar (binutils)" >&2; return; }
    ( cd "$root/DEBIAN" && tar --owner=0 --group=0 -czf ../../control.tar.gz ./* )
    ( cd "$root" && tar --owner=0 --group=0 --exclude=./DEBIAN -cJf ../data.tar.xz . )
    echo "2.0" > "$work/debian-binary"
    rm -f "$out"
    ( cd "$work" && ar rc "../../$out" debian-binary control.tar.gz data.tar.xz )
  fi
  rm -rf "$work"
  echo "    $out ($(du -h "$out" | cut -f1))"
}

# --- .rpm
make_rpm() {
  if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "    skipped .rpm: needs rpmbuild (dnf install rpm-build / apt install rpm / pacman -S rpm-tools)" >&2
    return
  fi
  local work rver rrel
  work=$(pwd)/build/rpm
  rver=${VERSION%%-*}                                       # 1.2.0-beta -> 1.2.0
  [ "$rver" = "$VERSION" ] && rrel=1 || rrel="0.${VERSION#*-}"   # beta: release 0.beta, sorts before 1
  rm -rf "$work"; mkdir -p "$work/root"
  stage_root "$work/root"
  local requires="" lib suffix=""
  case "$ARCH" in x86_64|aarch64|ppc64le|s390x) suffix="()(64bit)" ;; esac
  for lib in "${RPM_REQUIRES[@]}"; do requires+="Requires: ${lib}${suffix}"$'\n'; done
  cat > "$work/prism.spec" <<EOF
Name:           prism
Version:        $rver
Release:        $rrel
Summary:        $SUMMARY
License:        Proprietary
URL:            https://github.com/norik-jusufi/Prism
Provides:       webclient
# Bundled app: don't scan /opt/prism for dependencies or strip it.
AutoReqProv:    no
$requires
%global debug_package %{nil}
%global __os_install_post %{nil}
%define _build_id_links none

%description
$DESCRIPTION

%install
cp -a $work/root/. %{buildroot}/

%post
$(printf '%s' "$POSTINST" | sed '1d;$d')

%preun
if [ \$1 -eq 0 ]; then $PRERM_REMOVE; fi

%postun
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true

%files
/opt/prism
/usr/bin/prism
/usr/share/applications/prism.desktop
/usr/share/icons/hicolor/256x256/apps/prism.png
/usr/share/prism
EOF
  rpmbuild -bb --quiet --target "$ARCH" --define "_topdir $work/top" "$work/prism.spec"
  local rpm
  rpm=$(find "$work/top/RPMS" -name '*.rpm' | head -1)
  mv "$rpm" dist/
  rm -rf "$work"
  echo "    dist/$(basename "$rpm") ($(du -h "dist/$(basename "$rpm")" | cut -f1))"
}

for f in $FORMATS; do
  case "$f" in
    deb) make_deb ;;
    rpm) make_rpm ;;
    *) echo "unknown format: $f (deb, rpm)" >&2; exit 2 ;;
  esac
done
