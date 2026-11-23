"""PRISM update check: is there a newer PRISM, or a newer Qt WebEngine?

Qt WebEngine bundles its own Chromium, and Chromium security fixes only reach
PRISM when Qt ships a new WebEngine release *and* this machine installs it.
So besides PRISM's own version, PRISM checks whether the WebEngine it runs
on is still the newest one available.

  PRISM        version.py on GitHub (repo + branch from deployment.json)
  WebEngine    the PyQt6-WebEngine-Qt6 package on PyPI (the Qt + Chromium
               build PyQt ships), compared with the one installed with pip.
               When Qt WebEngine comes from the system (e.g. Arch's
               qt6-webengine), the system's package manager updates it and
               this check is skipped.

Checks run on a worker thread a few seconds after start and then twice a day,
through encrypted DNS when that is on. Nothing about the user is sent: these
are two plain GETs for public files. Turn them off with "updateCheck": false
in deployment.json.

One-click update (installed Windows copies only): "Install update" on the
dashboard downloads PRISM-Setup-<version>.exe from the GitHub release tagged
v<version>, checks its size and SHA-256 against what GitHub reports, runs it
silently (/RELAUNCH starts PRISM again afterwards) and quits PRISM so the
installer can replace its files. Source copies update with git pull.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from dohproxy import urllib_handlers
from paths import APP_DIR, FROZEN, PACKAGED
from edition import DEPLOYMENT
from version import VERSION

FIRST_CHECK_MS = 8_000
CHECK_EVERY_MS = 12 * 3600 * 1000
USER_AGENT = "PRISM-update-check"
PYPI_PACKAGE = "PyQt6-WebEngine-Qt6"
SETUP_ASSET = re.compile(r"^PRISM-Setup-[\w.\-]+\.exe$", re.I)
SETUP_MAX_BYTES = 1024 * 1024 * 1024          # sanity cap for the download
# GitHub serves release files from github.com, then redirects to its file CDN.
DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.0.3-beta' -> (1, 0, 3). Pre-release labels are ignored."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def engine_info() -> dict:
    """The Qt WebEngine / Chromium this PRISM is running on."""
    from PyQt6 import QtWebEngineCore as core
    info = {"qt": "", "chromium": "", "patch": ""}
    for key, fn in (("qt", "qWebEngineVersion"), ("chromium", "qWebEngineChromiumVersion"),
                    ("patch", "qWebEngineChromiumSecurityPatchVersion")):
        if hasattr(core, fn):
            try:
                info[key] = str(getattr(core, fn)())
            except Exception:  # noqa: BLE001 - informational only
                pass
    return info


def in_venv() -> bool:
    return sys.prefix != sys.base_prefix


def pip_engine_version() -> str | None:
    """Version of the pip-installed Qt WebEngine build, or None if the
    running WebEngine comes from the system."""
    from importlib import metadata
    try:
        dist = metadata.distribution(PYPI_PACKAGE)
    except metadata.PackageNotFoundError:
        return None
    # Only count it if it is the WebEngine actually in use (same environment as PyQt6).
    import PyQt6
    pyqt_dir = str(PyQt6.__path__[0])
    try:
        located = str(dist.locate_file("PyQt6"))
    except Exception:  # noqa: BLE001
        return dist.version
    return dist.version if located == pyqt_dir else None


def _opener():
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                                       *urllib_handlers())


def _get(url: str, accept: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
    if accept:
        headers["Accept"] = accept
    with _opener().open(urllib.request.Request(url, headers=headers), timeout=15) as resp:
        return resp.read(256 * 1024)


# ---------------------------------------------------------------- one-click update
def can_self_update() -> bool:
    """True for a copy installed with PRISM-Setup.exe on Windows (it has the
    installer's uninstaller next to it): those can update themselves."""
    return FROZEN and sys.platform == "win32" and (APP_DIR / "unins000.exe").exists()


def installed_for_all_users() -> bool:
    """Installed in Program Files ("for all users"): the update needs admin rights."""
    app = str(APP_DIR).lower().rstrip("\\") + "\\"
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base and app.startswith(base.lower().rstrip("\\") + "\\"):
            return True
    return False


def release_setup(version: str) -> dict:
    """The installer attached to the GitHub release v<version>: name, url, size, sha256."""
    repo = DEPLOYMENT["updateRepo"]
    tag = version if version.startswith("v") else f"v{version}"
    try:
        rel = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
                              accept="application/vnd.github+json"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"the {tag} release isn't on GitHub yet, try again later") from None
        raise
    for asset in rel.get("assets", []):
        if SETUP_ASSET.match(asset.get("name", "")):
            digest = asset.get("digest") or ""
            return {"name": asset["name"], "url": asset["browser_download_url"], "size": int(asset["size"]),
                    "sha256": digest[7:].lower() if digest.startswith("sha256:") else ""}
    raise ValueError(f"release {tag} has no PRISM-Setup .exe attached")


def download_setup(info: dict, dest_dir: Path, progress) -> Path:
    """Download the installer to dest_dir, checking size and SHA-256. progress(0..100)."""
    url = urlparse(info["url"])
    if url.scheme != "https" or url.hostname not in DOWNLOAD_HOSTS:
        raise ValueError(f"unexpected download address {info['url']}")
    if not SETUP_ASSET.match(info["name"]) or not 0 < info["size"] <= SETUP_MAX_BYTES:
        raise ValueError("unexpected installer file")
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("PRISM-Setup-*"):        # left over from earlier updates
        try:
            old.unlink()
        except OSError:
            pass
    final = dest_dir / info["name"]
    part = final.with_name(final.name + ".part")
    digest = hashlib.sha256()
    done = 0
    req = urllib.request.Request(info["url"], headers={"User-Agent": USER_AGENT})
    with _opener().open(req, timeout=30) as resp, open(part, "wb") as out:
        while chunk := resp.read(1024 * 1024):
            done += len(chunk)
            if done > info["size"]:
                break
            digest.update(chunk)
            out.write(chunk)
            progress(int(done * 100 / info["size"]))
    if done != info["size"]:
        part.unlink(missing_ok=True)
        raise ValueError(f"download incomplete ({done:,} of {info['size']:,} bytes)")
    if info["sha256"] and digest.hexdigest() != info["sha256"]:
        part.unlink(missing_ok=True)
        raise ValueError("download damaged: its checksum doesn't match the release")
    part.replace(final)
    return final


def setup_command(path: Path) -> list[str]:
    """Silent update in the same install mode as this copy; /RELAUNCH restarts PRISM after."""
    mode = "/ALLUSERS" if installed_for_all_users() else "/CURRENTUSER"
    return [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", mode, "/RELAUNCH"]


def run_setup(path: Path) -> None:
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    subprocess.Popen(setup_command(path), close_fds=True, creationflags=flags)


def latest_prism() -> str:
    repo, branch = DEPLOYMENT["updateRepo"], DEPLOYMENT["updateBranch"]
    src = _get(f"https://raw.githubusercontent.com/{repo}/{branch}/version.py").decode("utf-8", "replace")
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', src, re.M)
    if not m:
        raise ValueError("no VERSION in version.py")
    return m.group(1)


def latest_engine() -> str:
    data = json.loads(_get(f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"))
    return data["info"]["version"]


class UpdateChecker(QObject):
    changed = pyqtSignal()
    quit_for_update = pyqtSignal()      # the installer is running: PRISM should exit now
    _result = pyqtSignal(dict)
    _downloaded = pyqtSignal(str, str)  # path, error

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.enabled = bool(DEPLOYMENT.get("updateCheck", True))
        self.engine = engine_info()
        self.engine["pip"] = pip_engine_version()
        self.state: dict = {"checked": 0, "prism": None, "engine": None, "errors": []}
        self._running = False
        self._result.connect(self._apply)
        self.install: dict = {"status": "idle", "progress": 0, "error": ""}
        self._downloaded.connect(self._on_downloaded)
        if self.enabled:
            QTimer.singleShot(FIRST_CHECK_MS, self.check)
            self._timer = QTimer(self, interval=CHECK_EVERY_MS)
            self._timer.timeout.connect(self.check)
            self._timer.start()

    def check(self) -> None:
        if self._running or not self.enabled:
            return
        self._running = True
        threading.Thread(target=self._run, daemon=True, name="update-check").start()

    def _run(self) -> None:
        out: dict = {"checked": int(time.time()), "prism": None, "engine": None, "errors": []}
        try:
            out["prism"] = latest_prism()
        except Exception as exc:  # noqa: BLE001 - offline, repo private, ...
            out["errors"].append(f"PRISM: {exc}")
        if self.engine["pip"]:
            try:
                out["engine"] = latest_engine()
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"Qt WebEngine: {exc}")
        self._result.emit(out)

    def _apply(self, out: dict) -> None:
        self._running = False
        self.state = out
        for e in out["errors"]:
            print(f"[prism] update check failed: {e}", file=sys.stderr)
        self.changed.emit()

    # --- one-click update
    def install_update(self) -> str:
        """Start downloading and installing the newer PRISM. Returns a message for a toast."""
        version = self.prism_update()
        if not version:
            return "PRISM is up to date"
        if not can_self_update():
            if PACKAGED:
                return "Update the prism package with your package manager"
            return "This copy can't update itself: run the new installer, or git pull"
        if self.install["status"] in ("downloading", "starting"):
            return "The update is already on its way"
        self.install = {"status": "downloading", "progress": 0, "error": "", "version": version}
        threading.Thread(target=self._download, args=(version,), daemon=True, name="update-download").start()
        self.changed.emit()
        return f"Downloading PRISM {version}..."

    def _download(self, version: str) -> None:
        from storage import data_dir
        try:
            info = release_setup(version)
            path = download_setup(info, data_dir() / "updates",
                                  lambda pct: self.install.__setitem__("progress", pct))
            self._downloaded.emit(str(path), "")
        except Exception as exc:  # noqa: BLE001 - offline, no release yet, bad file...
            self._downloaded.emit("", str(exc))

    def _on_downloaded(self, path: str, error: str) -> None:
        if not error:
            try:
                run_setup(Path(path))
            except OSError as exc:
                error = f"couldn't start the installer: {exc}"
        if error:
            print(f"[prism] update failed: {error}", file=sys.stderr)
            self.install = {**self.install, "status": "error", "error": error}
            self.changed.emit()
            return
        self.install = {**self.install, "status": "starting", "progress": 100}
        self.changed.emit()
        self.quit_for_update.emit()

    # --- what the UI shows
    def prism_update(self) -> str | None:
        latest = self.state.get("prism")
        return latest if latest and parse_version(latest) > parse_version(VERSION) else None

    def engine_update(self) -> str | None:
        latest = self.state.get("engine")
        current = self.engine.get("pip")
        if not latest or not current:
            return None
        return latest if parse_version(latest) > parse_version(current) else None

    @staticmethod
    def how_to_update_engine() -> str:
        if FROZEN:
            return "the next PRISM installer (each build bundles the Qt WebEngine it was made with)"
        where = " in PRISM's .venv" if in_venv() else ""
        return f"pip install -r requirements.txt{where} once the pins there are raised"

    def snapshot(self) -> dict:
        prism, engine = self.prism_update(), self.engine_update()
        notes = []
        if prism:
            if can_self_update():
                how = "Install it with one click: PRISM restarts by itself."
            elif PACKAGED == "pacman":
                how = "In your PRISM clone: git pull, then makepkg -si in packaging/arch, then restart."
            elif PACKAGED:
                how = "Update the prism package with your package manager, then restart."
            elif FROZEN:
                how = "Run the new PRISM installer, then restart."
            else:
                how = "Run git pull in the PRISM folder, then restart."
            notes.append({"kind": "prism", "text": f"PRISM {prism} is out (you have {VERSION}). {how}"})
        if engine:
            notes.append({"kind": "engine", "text": f"Qt WebEngine {engine} is out (you run {self.engine['pip']}): "
                                                    f"it carries Chromium security fixes. Update with "
                                                    f"{self.how_to_update_engine()}."})
        return {"version": VERSION, "engine": self.engine, "enabled": self.enabled,
                "checked": self.state.get("checked", 0), "notes": notes,
                "install": {**self.install, "available": bool(prism) and can_self_update()}}
