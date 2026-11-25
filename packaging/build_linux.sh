#!/usr/bin/env bash
# Build PRISM for Linux:
#   dist/PRISM/PRISM                                   the browser executable (folder app)
#   dist/PRISM-<version>-linux-<arch>-setup.run        the installer (one file, any distro)
#   dist/prism_<version>_<arch>.deb                    Debian / Ubuntu / Mint package
#   dist/prism-<version>.<arch>.rpm                    Fedora / RHEL / openSUSE package (needs rpmbuild)
#
# Usage:  packaging/build_linux.sh
#   PYTHON=python3.14      Python to build with (default: python3)
#   SKIP_BLOCKLISTS=1      don't download fresh blocklists before bundling
#   PACKAGES="deb rpm"     distro packages to make (PACKAGES="" for none)
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}
VENV=build/venv
ARCH=$(uname -m)

echo "==> Build environment ($VENV)"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check -q -r requirements.txt -r packaging/requirements-build.txt

if [ "${SKIP_BLOCKLISTS:-0}" != 1 ]; then
  echo "==> Fresh blocklists (bundled into the build)"
  "$VENV/bin/python" update_blocklists.py || echo "    some lists failed; building with what is there"
fi

echo "==> PyInstaller"
"$VENV/bin/python" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build/pyinstaller packaging/prism.spec

VERSION=$("$VENV/bin/python" -c 'from version import VERSION; print(VERSION)')
echo "==> Self-test of the built executable"
dist/PRISM/PRISM --version

# Qt 6.12's wheels need glibc 2.34; nothing else in the bundle may need more,
# or the installers stop working on Ubuntu 22.04, Debian 12 and RHEL 9. A
# Python built on a newer distro (e.g. Arch's own) would: build with a
# portable one (uv python install 3.14) and PYTHON=<its python3.14>.
if command -v objdump >/dev/null 2>&1; then
  MAX_GLIBC=2.34
  need=$(find dist/PRISM -type f \( -name '*.so*' -o -name PRISM -o -name QtWebEngineProcess \) \
           -exec objdump -T {} + 2>/dev/null | grep -o 'GLIBC_2\.[0-9]*' | sort -uV | tail -1)
  need=${need#GLIBC_}
  echo "==> Newest glibc the build needs: ${need:-unknown} (limit $MAX_GLIBC)"
  if [ -n "$need" ] && [ "$(printf '%s\n%s\n' "$need" "$MAX_GLIBC" | sort -V | tail -1)" != "$MAX_GLIBC" ] \
       && [ "${ALLOW_NEW_GLIBC:-0}" != 1 ]; then
    echo "    Too new: these installers would only run on distros with glibc $need+." >&2
    echo "    Build with a portable Python (see above), or ALLOW_NEW_GLIBC=1 for a local-only build." >&2
    exit 1
  fi
fi

echo "==> Installer"
STAGE=build/installer-stage
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a dist/PRISM "$STAGE/PRISM"
cp packaging/linux/install.sh "$STAGE/install.sh"
cp packaging/linux/apparmor.sh "$STAGE/apparmor.sh"
cp assets/icon.png "$STAGE/icon.png"
chmod +x "$STAGE/install.sh"
OUT="dist/PRISM-${VERSION}-linux-${ARCH}-setup.run"
{
  sed -e "s/@VERSION@/${VERSION}/" -e "s/@ARCH@/${ARCH}/" packaging/linux/setup_header.sh
  tar -C "$STAGE" -czf - .
} > "$OUT"
chmod +x "$OUT"
rm -rf "$STAGE"

if [ -n "${PACKAGES-deb rpm}" ]; then
  echo "==> Distro packages"
  # shellcheck disable=SC2086
  packaging/linux/make_packages.sh ${PACKAGES-deb rpm}
fi

echo
echo "Done."
echo "  executable: dist/PRISM/PRISM"
echo "  installer:  $OUT ($(du -h "$OUT" | cut -f1))"
ls dist/*.deb dist/*.rpm 2>/dev/null | sed 's/^/  package:    /' || true
