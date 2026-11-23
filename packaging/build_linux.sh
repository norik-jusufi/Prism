#!/usr/bin/env bash
# Build PRISM for Linux:
#   dist/PRISM/PRISM                                   the browser executable (folder app)
#   dist/PRISM-<version>-linux-<arch>-setup.run        the installer (one file)
#
# Usage:  packaging/build_linux.sh
#   PYTHON=python3.14      Python to build with (default: python3)
#   SKIP_BLOCKLISTS=1      don't download fresh blocklists before bundling
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

echo "==> Installer"
STAGE=build/installer-stage
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a dist/PRISM "$STAGE/PRISM"
cp packaging/linux/install.sh "$STAGE/install.sh"
cp assets/icon.png "$STAGE/icon.png"
chmod +x "$STAGE/install.sh"
OUT="dist/PRISM-${VERSION}-linux-${ARCH}-setup.run"
{
  sed -e "s/@VERSION@/${VERSION}/" -e "s/@ARCH@/${ARCH}/" packaging/linux/setup_header.sh
  tar -C "$STAGE" -czf - .
} > "$OUT"
chmod +x "$OUT"
rm -rf "$STAGE"

echo
echo "Done."
echo "  executable: dist/PRISM/PRISM"
echo "  installer:  $OUT ($(du -h "$OUT" | cut -f1))"
