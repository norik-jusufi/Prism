#!/usr/bin/env bash
# Build PRISM for macOS:
#   dist/PRISM.app                                     the app (drag to Applications)
#   dist/PRISM-<version>-macos-<arch>.dmg              the disk image to hand out
#
# Build on a Mac of the target architecture (arm64 for Apple silicon, x86_64
# for Intel): PyInstaller can't cross-compile.
#
# Usage:  packaging/build_macos.sh
#   PYTHON=python3.14      Python to build with (default: python3; python.org or Homebrew)
#   SKIP_BLOCKLISTS=1      don't download fresh blocklists before bundling
#   SIGN_IDENTITY="Developer ID Application: ..."   sign with your Apple certificate
#                          (default: ad-hoc signature, fine on your own Macs;
#                          others get Gatekeeper's "unidentified developer" warning)
#   NOTARY_PROFILE=name    also notarize with `xcrun notarytool` (needs SIGN_IDENTITY;
#                          create the profile once with `xcrun notarytool store-credentials`)
set -euo pipefail
cd "$(dirname "$0")/.."

[ "$(uname -s)" = Darwin ] || { echo "Run this on macOS (Linux: packaging/build_linux.sh)." >&2; exit 1; }

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

echo "==> App icon (build/PRISM.icns)"
ICONSET=build/PRISM.iconset
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size assets/icon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size * 2)) $((size * 2)) assets/icon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o build/PRISM.icns
rm -rf "$ICONSET"

echo "==> PyInstaller"
"$VENV/bin/python" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build/pyinstaller packaging/prism.spec

APP=dist/PRISM.app
VERSION=$("$VENV/bin/python" -c 'from version import VERSION; print(VERSION)')
echo "==> Self-test of the built app"
"$APP/Contents/MacOS/PRISM" --version

echo "==> Code signature"
if [ -n "${SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP"
else
  # Apple silicon refuses to run unsigned code; an ad-hoc signature is enough
  # on the Mac that built it (and on others after right-click > Open once).
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"

echo "==> Disk image"
DMG="dist/PRISM-${VERSION}-macos-${ARCH}.dmg"
STAGE=build/dmg-stage
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"        # drag PRISM onto Applications to install
hdiutil create -quiet -volname "PRISM $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
[ -n "${SIGN_IDENTITY:-}" ] && codesign --force --sign "$SIGN_IDENTITY" "$DMG"

if [ -n "${NOTARY_PROFILE:-}" ]; then
  [ -n "${SIGN_IDENTITY:-}" ] || { echo "NOTARY_PROFILE needs SIGN_IDENTITY" >&2; exit 1; }
  echo "==> Notarization"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi

echo
echo "Done."
echo "  app:         $APP"
echo "  disk image:  $DMG ($(du -h "$DMG" | cut -f1))"
