# PyInstaller spec for PRISM: one spec for Windows, Linux and macOS.
#
# Builds a folder app (dist/PRISM/) holding the PRISM executable and what it
# needs (Python, Qt, Qt WebEngine's Chromium, ui/, assets/, blocklists/).
# On macOS it also wraps that into dist/PRISM.app, registered as a web
# browser (http/https links, HTML and PDF files).
# A folder build, not --onefile: Qt WebEngine is ~200 MB, and a one-file
# build would unpack all of it to a temp folder on every start.
#
# Don't run this directly: packaging/build_linux.sh, packaging/build_macos.sh
# and packaging\build_windows.bat set up the build environment first.

import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).resolve().parent          # noqa: F821 - SPECPATH is set by PyInstaller
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
VERSION = re.search(r'VERSION\s*=\s*"([^"]+)"', (ROOT / "version.py").read_text(encoding="utf-8")).group(1)

datas = [
    (str(ROOT / "ui"), "ui"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "blocklists"), "blocklists"),   # builtin + whatever update_blocklists.py downloaded
]
# updates.py reads the Qt WebEngine version from the package metadata to know
# when a newer Chromium (security fixes) is out.
datas += copy_metadata("PyQt6-WebEngine-Qt6")
datas += copy_metadata("anthropic")

a = Analysis(                                   # noqa: F821
    [str(ROOT / "prism.py")],
    pathex=[str(ROOT)],
    datas=datas,
    # Imported lazily (only when the edition/feature is on); list them so the
    # build always has them.
    hiddenimports=["designai", "terminal", "vault", "update_blocklists", "sounds"],
    excludes=["tkinter", "unittest", "pydoc_data"],
    noarchive=False,
)
# The intro's sounds (sounds.py) play WAVs through QSoundEffect, which needs
# Qt Multimedia's own audio output but none of its media-player plugins. Leave
# out the FFmpeg plugin and its libraries (~20 MB).
a.binaries = [b for b in a.binaries
              if "plugins/multimedia/" not in b[0].replace("\\", "/")
              and not Path(b[0]).name.lower().startswith(("avcodec", "avformat", "avutil", "swresample", "swscale"))]

pyz = PYZ(a.pure)                               # noqa: F821

exe = EXE(                                      # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PRISM",
    icon=str(ROOT / "assets" / ("icon.ico" if WINDOWS else "icon.png")) if not MACOS else None,
    console=False,                              # a GUI app: no console window on Windows
    upx=False,                                  # UPX breaks Qt WebEngine and trips antivirus
    strip=False,
)

coll = COLLECT(                                 # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PRISM",
)

if MACOS:
    # build_macos.sh makes the .icns from assets/icon.png (sips + iconutil).
    icns = os.environ.get("PRISM_ICNS") or str(ROOT / "build" / "PRISM.icns")
    numeric = re.match(r"\d+(\.\d+)*", VERSION).group(0)      # "1.2.0-beta" -> "1.2.0"
    app = BUNDLE(                               # noqa: F821
        coll,
        name="PRISM.app",
        icon=icns if Path(icns).is_file() else None,
        bundle_identifier="com.synterra.prism",
        version=numeric,
        info_plist={
            "CFBundleName": "PRISM",
            "CFBundleDisplayName": "PRISM",
            "CFBundleShortVersionString": numeric,
            "CFBundleVersion": numeric,
            "NSHumanReadableCopyright": "Synterra",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "LSMinimumSystemVersion": "13.0",          # Qt 6.12 needs macOS 13 Ventura or later
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,   # follow dark mode
            # A web browser: macOS lists PRISM under Default web browser
            # (System Settings > Desktop & Dock) and sends it clicked links
            # as Apple events (see instance.AppleEvents).
            "CFBundleURLTypes": [{
                "CFBundleURLName": "Web site URL",
                "CFBundleURLSchemes": ["http", "https"],
                "CFBundleTypeRole": "Viewer",
            }],
            "CFBundleDocumentTypes": [
                {"CFBundleTypeName": "HTML document", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
                 "LSItemContentTypes": ["public.html", "public.xhtml"]},
                {"CFBundleTypeName": "PDF document", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
                 "LSItemContentTypes": ["com.adobe.pdf"]},
                {"CFBundleTypeName": "SVG image", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
                 "LSItemContentTypes": ["public.svg-image"]},
            ],
            # Without these, macOS ends the app the moment a site asks for
            # the camera, microphone or location (PRISM still asks the user
            # per site first: Permission Control Center).
            "NSCameraUsageDescription": "A website you allowed wants to use the camera.",
            "NSMicrophoneUsageDescription": "A website you allowed wants to use the microphone.",
            "NSLocationWhenInUseUsageDescription": "A website you allowed wants to know your location.",
        },
    )
