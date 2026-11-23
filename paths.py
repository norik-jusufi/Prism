"""Where PRISM's own files are, whether it runs from source or as a built app.

From source (python prism.py) everything is in the repository folder.

As a built app (PyInstaller, see packaging/) there are three places:
  RESOURCES  the read-only bundle: ui/, assets/, blocklists/ (the lists
             shipped with this build). Inside the install folder.
  APP_DIR    the folder holding the PRISM executable. deployment.json goes
             here, so an installer (or IT) can set the edition per install.
  data dir   per-user and writable (storage.data_dir()). Lists downloaded with
             `PRISM --update-blocklists` go to <data dir>/blocklists, since
             the install folder usually isn't writable.

From a system package (Arch: packaging/arch/PKGBUILD) PRISM runs from source
in a read-only folder (/usr/lib/prism) holding a `.packaged` file that names
the package manager. Downloaded lists go to the data dir there too.
"""

from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
SOURCE_DIR = Path(__file__).resolve().parent
RESOURCES = Path(getattr(sys, "_MEIPASS", SOURCE_DIR)) if FROZEN else SOURCE_DIR
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else SOURCE_DIR


def _package_manager() -> str:
    try:
        return (SOURCE_DIR / ".packaged").read_text(encoding="utf-8").strip() or "system"
    except OSError:
        return ""


PACKAGED = "" if FROZEN else _package_manager()     # e.g. "pacman"; "" when not a system package


def user_blocklists_dir() -> Path | None:
    """Writable folder for downloaded lists in a built app or a system
    package; None from a repository checkout (there they go to
    blocklists/downloaded in the repository)."""
    if not (FROZEN or PACKAGED):
        return None
    from storage import data_dir
    return data_dir() / "blocklists"
