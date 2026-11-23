"""PRISM downloads: where files go, the "Save download" popup, and the list of
this session's downloads (panel section "downloads", Ctrl+J).

settings.json "downloads":
  mode    "ask"     PRISM's own popup: rename the file, pick a folder from
                    Downloads / Desktop / Documents / recent folders, or
                    Browse... for the system folder picker  (the default)
          "system"  the standard Save As dialog of the operating system
          "auto"    no question: straight into the default folder
  dir     the default folder ("" = the system Downloads folder)
  recent  the last few folders downloads were saved to

Qt WebEngine cancels a download that isn't accepted inside its signal
handler, so the popup is a modal dialog shown right there.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QPoint, QSize, QStandardPaths, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFontMetrics, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                             QVBoxLayout, QWidget)

if TYPE_CHECKING:
    from window import PrismWindow

MODES = {"ask": "PRISM popup", "system": "System save dialog", "auto": "Save to default folder"}
MAX_RECENT = 5
# What PRISM shows itself when you open a finished download; anything else
# opens in its usual app.
VIEWABLE = {".pdf", ".html", ".htm", ".xhtml", ".shtml", ".svg", ".txt", ".json", ".xml", ".log", ".md",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico", ".mp4", ".webm", ".mp3",
            ".ogg", ".wav", ".mhtml", ".mht"}


def system_downloads() -> Path:
    loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return Path(loc) if loc else Path.home() / "Downloads"


def _place(kind: QStandardPaths.StandardLocation) -> Path | None:
    loc = QStandardPaths.writableLocation(kind)
    return Path(loc) if loc else None


def unique_path(folder: Path, name: str) -> Path:
    """folder/name, or "name (1).ext", "name (2).ext", ... when that is taken."""
    path = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while path.exists():
        path = folder / f"{stem} ({n}){suffix}"
        n += 1
    return path


def safe_name(name: str) -> str:
    """A file name without folders or characters Windows refuses."""
    name = name.replace("/", "_").replace("\\", "_")
    for ch in '<>:"|?*':
        name = name.replace(ch, "_")
    name = "".join(c for c in name if ord(c) >= 32).strip(" .")
    return name or "download"


def human_size(n: int) -> str:
    if n < 0:
        return "unknown size"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def show_in_folder(path: Path) -> None:
    """Open the file's folder with the file selected (Windows), or just the folder."""
    if sys.platform == "win32" and path.is_file():
        subprocess.Popen(["explorer", "/select,", str(path)])        # noqa: S603,S607
    else:
        open_folder(path.parent)


def open_folder(folder: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


# ----------------------------------------------------------------- popup
DIALOG_QSS = """
#card { background:#07110c; border:1px solid #1f5537; border-radius:10px; }
QLabel { color:#a9c9b5; font-family:'Cascadia Code','Consolas',monospace; font-size:12px; }
#kicker { color:#36f59b; font-size:11px; letter-spacing:1px; }
#title { color:#e8f5ec; font-size:15px; font-weight:bold; }
#meta, #section, #hint { color:#5f8270; font-size:11px; }
#section { letter-spacing:1px; padding-top:6px; }
#path { color:#5f8270; font-size:11px; }
QLineEdit { background:#040a07; color:#e8f5ec; border:1px solid #1f5537; border-radius:6px; padding:8px 10px;
            font-family:'Cascadia Code','Consolas',monospace; font-size:13px; selection-background-color:#1fa866; }
QLineEdit:focus { border-color:#36f59b; }
QListWidget { background:transparent; border:none; outline:none; }
QListWidget::item { border:1px solid #163826; border-radius:6px; margin:2px 0; padding:0; }
QListWidget::item:hover { background:#0b1a12; border-color:#1f5537; }
QListWidget::item:selected { background:#0f2a1c; border-color:#36f59b; }
QPushButton { background:#0b1a12; color:#d6f5e2; border:1px solid #1f5537; border-radius:6px; padding:8px 16px;
              font-family:'Cascadia Code','Consolas',monospace; font-size:12px; }
QPushButton:hover { border-color:#36f59b; color:#36f59b; }
QPushButton:focus { border-color:#36f59b; }
#primary { background:#36f59b; color:#04120a; border-color:#36f59b; font-weight:bold; }
#primary:hover { background:#74ff7a; color:#04120a; }
#close { background:transparent; border:none; color:#5f8270; font-size:15px; padding:2px 8px; }
#close:hover { color:#36f59b; }
QCheckBox { color:#a9c9b5; font-family:'Cascadia Code','Consolas',monospace; font-size:11px; spacing:8px; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #1f5537; border-radius:3px; background:#040a07; }
QCheckBox::indicator:checked { background:#36f59b; border-color:#36f59b; }
QComboBox { background:#040a07; color:#d6f5e2; border:1px solid #1f5537; border-radius:6px; padding:5px 10px;
            font-family:'Cascadia Code','Consolas',monospace; font-size:11px; }
QComboBox:hover { border-color:#36f59b; }
QComboBox QAbstractItemView { background:#07110c; color:#d6f5e2; border:1px solid #1f5537;
                              selection-background-color:#0f2a1c; selection-color:#36f59b; }
"""


ROW_H = 54                   # one folder row in the popup, margins included


class _PlaceRow(QWidget):
    def __init__(self, icon: str, name: str, path: Path, tag: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(12)
        ic = QLabel(icon)
        ic.setFixedWidth(18)
        ic.setStyleSheet("color:#36f59b; font-size:14px;")
        col = QVBoxLayout()
        col.setSpacing(1)
        top = QLabel(name + (f"   <span style='color:#1fa866'>{tag}</span>" if tag else ""))
        top.setStyleSheet("color:#e8f5ec; font-size:12px;")
        top.setTextFormat(Qt.TextFormat.RichText)
        sub = QLabel(objectName="path")
        sub.setText(QFontMetrics(sub.font()).elidedText(str(path), Qt.TextElideMode.ElideMiddle, 380))
        sub.setToolTip(str(path))
        col.addWidget(top)
        col.addWidget(sub)
        lay.addWidget(ic)
        lay.addLayout(col, 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class SaveDialog(QDialog):
    """PRISM's own "where should this go?" popup."""

    def __init__(self, parent: QWidget, name: str, size: int, source: str, settings):
        super().__init__(parent)
        self.settings = settings
        conf = settings["downloads"]
        self.result_path: Path | None = None
        self._drag: QPoint | None = None
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowTitle("Save download")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        card = QFrame(objectName="card")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(Qt.GlobalColor.black)
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 16, 22, 20)
        lay.setSpacing(8)

        head = QHBoxLayout()
        kicker = QLabel("⤓  SAVE DOWNLOAD", objectName="kicker")
        close = QPushButton("✕", objectName="close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        head.addWidget(kicker)
        head.addStretch(1)
        head.addWidget(close)
        lay.addLayout(head)

        self.name = QLineEdit(name)
        self.name.setAccessibleName("File name")
        stem = len(Path(name).stem) if Path(name).suffix else len(name)
        self.name.setSelection(0, stem)                 # typing replaces the name, keeps the extension
        lay.addWidget(self.name)
        meta = QLabel(f"{human_size(size)}" + (f"  ·  from {source}" if source else ""), objectName="meta")
        lay.addWidget(meta)

        lay.addWidget(QLabel("SAVE TO", objectName="section"))
        self.places = QListWidget()
        self.places.setAccessibleName("Folders")
        self.places.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.places.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        default = Path(conf.get("dir") or system_downloads())
        seen: set[str] = set()
        rows: list[tuple[str, str, Path, str]] = [("★", default.name or str(default), default, "default")]
        for icon, label, kind in (("⤓", "Downloads", QStandardPaths.StandardLocation.DownloadLocation),
                                  ("▭", "Desktop", QStandardPaths.StandardLocation.DesktopLocation),
                                  ("▤", "Documents", QStandardPaths.StandardLocation.DocumentsLocation)):
            path = _place(kind)
            if path:
                rows.append((icon, label, path, ""))
        for folder in conf.get("recent", []):
            rows.append(("↺", Path(folder).name or folder, Path(folder), "recent"))
        for icon, label, path, tag in rows:
            key = os.path.normcase(str(path))
            if key in seen or (tag == "recent" and not path.is_dir()):
                continue
            seen.add(key)
            self._add_place(icon, label, path, tag)
        self.places.setCurrentRow(0)
        self.places.setFixedHeight(min(5, self.places.count()) * ROW_H + 4)
        self.places.itemDoubleClicked.connect(lambda _i: self.accept_save())
        lay.addWidget(self.places)

        browse = QPushButton("Browse…  (pick any folder)")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self.browse)
        lay.addWidget(browse)

        self.make_default = QCheckBox("Make the chosen folder my default")
        lay.addWidget(self.make_default)

        lay.addSpacing(6)
        foot = QHBoxLayout()
        foot.addWidget(QLabel("Next time:", objectName="hint"))
        self.mode = QComboBox()
        self.mode.setAccessibleName("What happens on the next download")
        for key, label in MODES.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(list(MODES).index("ask"))
        foot.addWidget(self.mode)
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save", objectName="primary")
        save.setDefault(True)
        save.clicked.connect(self.accept_save)
        foot.addWidget(cancel)
        foot.addWidget(save)
        lay.addLayout(foot)

        QShortcut(QKeySequence("Escape"), self, activated=self.reject)
        self.setFixedWidth(520)
        self.name.setFocus()

    def _add_place(self, icon: str, label: str, path: Path, tag: str) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        row = _PlaceRow(icon, label, path, tag)
        item.setSizeHint(QSize(0, ROW_H - 4))
        self.places.addItem(item)
        self.places.setItemWidget(item, row)
        return item

    def browse(self) -> None:
        start = self.places.currentItem().data(Qt.ItemDataRole.UserRole) if self.places.currentItem() else ""
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for this download", start)
        if not folder:
            return
        path = Path(folder)
        for i in range(self.places.count()):
            if os.path.normcase(self.places.item(i).data(Qt.ItemDataRole.UserRole)) == os.path.normcase(str(path)):
                self.places.setCurrentRow(i)
                return
        item = self._add_place("▸", path.name or str(path), path, "chosen")
        self.places.setCurrentItem(item)
        self.places.setFixedHeight(min(6, self.places.count()) * ROW_H + 4)
        self.adjustSize()

    def accept_save(self) -> None:
        item = self.places.currentItem()
        name = safe_name(self.name.text())
        if item is None:
            return
        folder = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.name.setToolTip(f"Can't write to {folder}")
            return
        self.result_path = unique_path(folder, name)
        conf = self.settings["downloads"]
        if self.make_default.isChecked():
            conf["dir"] = str(folder)
        conf["mode"] = self.mode.currentData()
        self.accept()

    # drag the frameless popup by its background
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):  # noqa: N802
        self._drag = None


# --------------------------------------------------------------- manager
class Downloads(QObject):
    """Decides where each download goes and keeps this session's list."""

    changed = pyqtSignal()

    def __init__(self, window: "PrismWindow"):
        super().__init__(window)
        self.w = window
        self.settings = window.settings
        conf = self.settings.data.setdefault("downloads", {})
        conf.setdefault("mode", "ask")
        conf.setdefault("dir", "")
        conf.setdefault("recent", [])
        self.items: list[dict] = []          # newest first; memory only
        self._n = 0

    @property
    def conf(self) -> dict:
        return self.settings["downloads"]

    def default_dir(self) -> Path:
        d = self.conf.get("dir")
        return Path(d) if d and Path(d).is_dir() else system_downloads()

    def set_mode(self, mode: str) -> None:
        if mode in MODES:
            self.conf["mode"] = mode
            self.settings.save()
            self.changed.emit()

    def choose_default_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.w, "Default download folder", str(self.default_dir()))
        if folder:
            self.conf["dir"] = folder
            self.settings.save()
            self.changed.emit()

    # ------------------------------------------------------------ requests
    def handle(self, download) -> None:
        """Called from the profile's downloadRequested: pick the target, then accept or cancel."""
        name = safe_name(download.suggestedFileName() or download.downloadFileName())
        mode = self.conf.get("mode", "ask")
        source = download.url().host() or download.url().scheme()
        target: Path | None
        if mode == "auto":
            target = unique_path(self.default_dir(), name)
        elif mode == "system":
            path, _ = QFileDialog.getSaveFileName(self.w, "Save download", str(self.default_dir() / name))
            target = Path(path) if path else None
        else:
            dlg = SaveDialog(self.w, name, download.totalBytes(), source, self.settings)
            dlg.adjustSize()
            dlg.move(self.w.geometry().center() - dlg.rect().center())
            target = dlg.result_path if dlg.exec() == QDialog.DialogCode.Accepted else None
        if target is None:
            download.cancel()
            self.settings.save()
            self.w.bridge.toast.emit(f"download cancelled: {name}")
            return

        download.setDownloadDirectory(str(target.parent))
        download.setDownloadFileName(target.name)
        download.accept()
        self._remember(target.parent)
        self._n += 1
        item = {"id": self._n, "name": target.name, "path": str(target), "url": download.url().toString(),
                "source": source, "received": 0, "total": download.totalBytes(), "state": "progress",
                "started": time.time(), "_d": download}
        self.items.insert(0, item)
        del self.items[50:]
        download.receivedBytesChanged.connect(lambda i=item, d=download: self._progress(i, d))
        download.isFinishedChanged.connect(lambda i=item, d=download: self._finished(i, d))
        self.w.bridge.toast.emit(f"downloading {target.name}")
        self.changed.emit()

    def _remember(self, folder: Path) -> None:
        recent = [f for f in self.conf.get("recent", []) if os.path.normcase(f) != os.path.normcase(str(folder))]
        if os.path.normcase(str(folder)) != os.path.normcase(str(self.default_dir())):
            recent.insert(0, str(folder))
        self.conf["recent"] = recent[:MAX_RECENT]
        self.settings.save()

    def _progress(self, item: dict, d) -> None:
        # No signal here (it fires per chunk): the panel refreshes the list every second.
        item["received"], item["total"] = d.receivedBytes(), d.totalBytes()

    def _finished(self, item: dict, d) -> None:
        state = d.state().name
        item["received"], item["total"] = d.receivedBytes(), d.totalBytes()
        item["state"] = {"DownloadCompleted": "done", "DownloadCancelled": "cancelled"}.get(state, "failed")
        item.pop("_d", None)
        if item["state"] == "done":
            self.w.bridge.toast.emit(f"saved {item['name']} to {Path(item['path']).parent}")
        elif item["state"] == "failed":
            self.w.bridge.toast.emit(f"download failed: {item['name']} ({d.interruptReasonString()})")
        self.changed.emit()

    # ------------------------------------------------------------- actions
    def find(self, item_id: int) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def open(self, item_id: int) -> None:
        item = self.find(item_id)
        if not item or item["state"] != "done":
            return
        path = Path(item["path"])
        if not path.exists():
            self.w.bridge.toast.emit(f"{path.name} was moved or deleted")
        elif path.suffix.lower() in VIEWABLE:
            self.w.open_external([QUrl.fromLocalFile(str(path)).toString()])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def reveal(self, item_id: int) -> None:
        item = self.find(item_id)
        if item:
            show_in_folder(Path(item["path"]))

    def cancel(self, item_id: int) -> None:
        item = self.find(item_id)
        if item and item.get("_d") is not None:
            item["_d"].cancel()

    def clear_finished(self) -> None:
        self.items = [i for i in self.items if i["state"] == "progress"]
        self.changed.emit()

    def summary(self) -> dict:
        return {
            "mode": self.conf.get("mode", "ask"),
            "modes": MODES,
            "dir": str(self.default_dir()),
            "items": [{k: v for k, v in i.items() if not k.startswith("_")} for i in self.items],
        }
