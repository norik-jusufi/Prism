# PyInstaller spec for PRISM: one spec for Windows and Linux.
#
# Builds a folder app (dist/PRISM/) holding the PRISM executable and what it
# needs (Python, Qt, Qt WebEngine's Chromium, ui/, assets/, blocklists/).
# A folder build, not --onefile: Qt WebEngine is ~200 MB, and a one-file
# build would unpack all of it to a temp folder on every start.
#
# Don't run this directly: packaging/build_linux.sh and
# packaging\build_windows.bat set up the build environment first.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).resolve().parent          # noqa: F821 - SPECPATH is set by PyInstaller
WINDOWS = sys.platform == "win32"

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
    icon=str(ROOT / "assets" / ("icon.ico" if WINDOWS else "icon.png")),
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
