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

from PyQt6.QtCore import QObject, QPoint, QRect, QRectF, QSize, QStandardPaths, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QColor, QDesktopServices, QFontMetrics, QKeySequence, QLinearGradient, QPainter,
                         QShortcut)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                             QGraphicsDropShadowEffect,
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
QLabel { color:#a9c9b5; font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:12px; }
#kicker { color:#36f59b; font-size:11px; letter-spacing:1px; }
#title { color:#e8f5ec; font-size:15px; font-weight:bold; }
#meta, #section, #hint { color:#5f8270; font-size:11px; }
#section { letter-spacing:1px; padding-top:6px; }
#path { color:#5f8270; font-size:11px; }
QLineEdit { background:#040a07; color:#e8f5ec; border:1px solid #1f5537; border-radius:6px; padding:8px 10px;
            font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:13px; selection-background-color:#1fa866; }
QLineEdit:focus { border-color:#36f59b; }
QListWidget { background:transparent; border:none; outline:none; }
QListWidget::item { border:1px solid #163826; border-radius:6px; margin:2px 0; padding:0; }
QListWidget::item:hover { background:#0b1a12; border-color:#1f5537; }
QListWidget::item:selected { background:#0f2a1c; border-color:#36f59b; }
QPushButton { background:#0b1a12; color:#d6f5e2; border:1px solid #1f5537; border-radius:6px; padding:8px 16px;
              font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:12px; }
QPushButton:hover { border-color:#36f59b; color:#36f59b; }
QPushButton:focus { border-color:#36f59b; }
#primary { background:#36f59b; color:#04120a; border-color:#36f59b; font-weight:bold; }
#primary:hover { background:#74ff7a; color:#04120a; }
#close { background:transparent; border:none; color:#5f8270; font-size:15px; padding:2px 8px; }
#close:hover { color:#36f59b; }
QCheckBox { color:#a9c9b5; font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:11px; spacing:8px; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #1f5537; border-radius:3px; background:#040a07; }
QCheckBox::indicator:checked { background:#36f59b; border-color:#36f59b; }
QComboBox { background:#040a07; color:#d6f5e2; border:1px solid #1f5537; border-radius:6px; padding:5px 10px;
            font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:11px; }
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
    progress = pyqtSignal()      # throttled: a few times a second while something downloads

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
        self._flyout: DownloadsFlyout | None = None
        self._last_done = 0.0                # when a download last finished (toolbar flash)
        self._tick = QTimer(self, interval=250)
        self._tick.timeout.connect(self._on_tick)

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
                "started": time.time(), "speed": 0.0, "_d": download, "_s": (time.monotonic(), 0)}
        self.items.insert(0, item)
        del self.items[50:]
        download.receivedBytesChanged.connect(lambda i=item, d=download: self._progress(i, d))
        download.isFinishedChanged.connect(lambda i=item, d=download: self._finished(i, d))
        self.w.bridge.toast.emit(f"downloading {target.name}")
        self._tick.start()
        self.changed.emit()
        self.progress.emit()

    def _remember(self, folder: Path) -> None:
        recent = [f for f in self.conf.get("recent", []) if os.path.normcase(f) != os.path.normcase(str(folder))]
        if os.path.normcase(str(folder)) != os.path.normcase(str(self.default_dir())):
            recent.insert(0, str(folder))
        self.conf["recent"] = recent[:MAX_RECENT]
        self.settings.save()

    def _progress(self, item: dict, d) -> None:
        # No signal here (it fires per chunk): _on_tick reports a few times a second.
        item["received"], item["total"] = d.receivedBytes(), d.totalBytes()
        t0, b0 = item["_s"]
        now = time.monotonic()
        if now - t0 >= 0.5:
            rate = (item["received"] - b0) / (now - t0)
            item["speed"] = rate if not item["speed"] else 0.6 * item["speed"] + 0.4 * rate
            item["_s"] = (now, item["received"])

    def _on_tick(self) -> None:
        if not any(i["state"] == "progress" for i in self.items):
            self._tick.stop()
        self.progress.emit()
        if self._flyout is not None and self._flyout.isVisible():
            self._flyout.refresh()

    def _finished(self, item: dict, d) -> None:
        state = d.state().name
        item["received"], item["total"] = d.receivedBytes(), d.totalBytes()
        item["state"] = {"DownloadCompleted": "done", "DownloadCancelled": "cancelled"}.get(state, "failed")
        item.pop("_d", None)
        item.pop("_s", None)
        item["speed"] = 0.0
        if item["state"] == "done":
            self._last_done = time.time()
            QTimer.singleShot(4200, self.progress.emit)      # end the toolbar's "done" flash
        self.progress.emit()
        if self._flyout is not None and self._flyout.isVisible():
            self._flyout.refresh()
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
        self.progress.emit()

    def summary(self) -> dict:
        return {
            "mode": self.conf.get("mode", "ask"),
            "modes": MODES,
            "dir": str(self.default_dir()),
            "items": [{k: v for k, v in i.items() if not k.startswith("_")} for i in self.items],
        }

    def badge(self) -> dict:
        """What the toolbar's downloads button shows: a progress ring while downloading."""
        active = [i for i in self.items if i["state"] == "progress"]
        known = [i for i in active if i["total"] > 0]
        total = sum(i["total"] for i in known)
        frac = (sum(i["received"] for i in known) / total) if total else -1
        return {"count": len(self.items), "active": len(active), "progress": round(frac, 4) if active else -1,
                "speed": round(sum(i.get("speed", 0) for i in active)),
                "justDone": time.time() - self._last_done < 4,
                "failed": any(i["state"] == "failed" for i in self.items[:1])}

    def show_flyout(self, anchor: QRect) -> None:
        if self._flyout is None:
            self._flyout = DownloadsFlyout(self)
        self._flyout.refresh()
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(anchor.right() - self._flyout.width() + 14, area.right() - self._flyout.width())
        self._flyout.move(max(area.left(), x), anchor.bottom() - 4)
        self._flyout.show()
        self._flyout.raise_()

def eta(item: dict) -> str:
    speed, left = item.get("speed", 0), item["total"] - item["received"]
    if item["total"] <= 0 or speed <= 1:
        return ""
    s = int(left / speed)
    if s < 60:
        return f"{s}s left"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s left"
    return f"{s // 3600}h {s % 3600 // 60}m left"


# --------------------------------------------------------------- flyout
FLYOUT_QSS = DIALOG_QSS + """
#flyhead { color:#36f59b; font-size:11px; letter-spacing:2px; }
#flycount { color:#5f8270; font-size:11px; }
#row { background:#040a07; border:1px solid #163826; border-radius:8px; }
#row[state="progress"] { border-color:#1f5537; }
#row[state="failed"], #row[state="cancelled"] { border-color:#3a1d22; }
#fname { color:#e8f5ec; font-size:12px; }
#fmeta { color:#5f8270; font-size:10.5px; }
#fmeta[state="failed"] { color:#ff5f6d; }
#pct { color:#36f59b; font-size:11px; font-weight:bold; }
#mini { background:transparent; border:1px solid #1f5537; border-radius:5px; padding:3px 9px; font-size:10.5px; }
#mini:hover { border-color:#36f59b; color:#36f59b; }
#link { background:transparent; border:none; color:#5f8270; padding:4px 2px; font-size:11px; }
#link:hover { color:#36f59b; }
#empty { color:#5f8270; font-size:11.5px; padding:18px 4px; }
"""


class _Bar(QWidget):
    """A thin glowing progress bar; a moving block when the size is unknown."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(6)
        self.value = 0.0          # 0..1, or -1 = unknown
        self.state = "progress"
        self._phase = 0.0

    def set(self, value: float, state: str) -> None:
        self.value, self.state = value, state
        self._phase = (self._phase + 0.04) % 1.0
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0b1a12"))
        p.drawRoundedRect(r, 2, 2)
        color = QColor({"done": "#36f59b", "failed": "#ff5f6d", "cancelled": "#5f8270"}.get(self.state, "#36f59b"))
        if self.state == "progress" and self.value < 0:
            w = r.width() * 0.25
            x = r.left() + (r.width() + w) * self._phase - w
            left = max(r.left(), x)
            fill = QRectF(left, r.top(), max(0.0, min(x + w, r.right()) - left), r.height())
        else:
            v = 1.0 if self.state != "progress" else max(0.0, min(1.0, self.value))
            fill = QRectF(r.left(), r.top(), r.width() * v, r.height())
        if fill.width() > 0:
            g = QLinearGradient(fill.left(), 0, fill.right(), 0)
            g.setColorAt(0, QColor("#1fa866") if self.state == "progress" else color)
            g.setColorAt(1, color)
            p.setBrush(g)
            p.drawRoundedRect(fill, 2, 2)
        p.end()


class _Row(QFrame):
    def __init__(self, mgr: "Downloads", item_id: int):
        super().__init__(objectName="row")
        self.mgr, self.id = mgr, item_id
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name = QLabel(objectName="fname")
        self.pct = QLabel(objectName="pct")
        top.addWidget(self.name, 1)
        top.addWidget(self.pct)
        lay.addLayout(top)
        self.bar = _Bar()
        lay.addWidget(self.bar)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.meta = QLabel(objectName="fmeta")
        bottom.addWidget(self.meta, 1)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, fn in (("open", "Open", mgr.open), ("show", "Show in folder", mgr.reveal),
                               ("cancel", "Cancel", mgr.cancel)):
            b = QPushButton(label, objectName="mini")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, fn=fn: self._act(fn))
            bottom.addWidget(b)
            self.buttons[key] = b
        lay.addLayout(bottom)

    def _act(self, fn) -> None:
        fn(self.id)
        if self.mgr._flyout is not None:
            self.mgr._flyout.refresh()

    def update_from(self, item: dict) -> None:
        state = item["state"]
        fm = QFontMetrics(self.name.font())
        self.name.setText(fm.elidedText(item["name"], Qt.TextElideMode.ElideMiddle, 250))
        self.name.setToolTip(item["path"])
        total, got = item["total"], item["received"]
        frac = got / total if total > 0 else -1
        self.bar.set(frac, state)
        if state == "progress":
            self.pct.setText(f"{frac * 100:.0f}%" if frac >= 0 else "...")
            parts = [f"{human_size(got)} of {human_size(total)}" if total > 0 else human_size(got)]
            if item.get("speed", 0) > 1:
                parts.append(f"{human_size(int(item['speed']))}/s")
            if eta(item):
                parts.append(eta(item))
            self.meta.setText("  ·  ".join(parts))
        else:
            self.pct.setText({"done": "✓", "failed": "✕", "cancelled": "–"}.get(state, ""))
            self.meta.setText({"done": f"{human_size(got)}  ·  {item['source']}",
                               "failed": "failed", "cancelled": "cancelled"}.get(state, state))
        for w in (self, self.meta):
            if w.property("state") != state:
                w.setProperty("state", state)
                w.style().unpolish(w)
                w.style().polish(w)
        self.buttons["open"].setVisible(state == "done")
        self.buttons["show"].setVisible(state == "done")
        self.buttons["cancel"].setVisible(state == "progress")


class DownloadsFlyout(QFrame):
    """Drops down from the toolbar's downloads button: this session's downloads, live."""

    def __init__(self, mgr: "Downloads"):
        super().__init__(mgr.w, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.mgr = mgr
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(FLYOUT_QSS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 18)
        card = QFrame(objectName="card")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(Qt.GlobalColor.black)
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("⤓  DOWNLOADS", objectName="flyhead"))
        head.addStretch(1)
        self.count = QLabel(objectName="flycount")
        head.addWidget(self.count)
        lay.addLayout(head)
        self.list = QVBoxLayout()
        self.list.setSpacing(6)
        lay.addLayout(self.list)
        self.empty = QLabel("No downloads in this session yet.", objectName="empty")
        lay.addWidget(self.empty)
        foot = QHBoxLayout()
        for label, fn in (("All downloads (Ctrl+J)", self._panel), ("Open folder", self._folder),
                          ("Clear finished", self._clear)):
            b = QPushButton(label, objectName="link")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            foot.addWidget(b)
            if label.startswith("All"):
                foot.addStretch(1)
        lay.addLayout(foot)
        self.rows: dict[int, _Row] = {}
        self.setFixedWidth(440)

    def _panel(self) -> None:
        self.hide()
        self.mgr.w.toggle_panel("downloads", force=True)

    def _folder(self) -> None:
        self.hide()
        open_folder(self.mgr.default_dir())

    def _clear(self) -> None:
        self.mgr.clear_finished()
        self.refresh()

    def refresh(self) -> None:
        items = self.mgr.items[:6]
        ids = [i["id"] for i in items]
        for rid in list(self.rows):
            if rid not in ids:
                self.rows.pop(rid).deleteLater()
        for pos, item in enumerate(items):
            row = self.rows.get(item["id"])
            if row is None:
                row = self.rows[item["id"]] = _Row(self.mgr, item["id"])
            self.list.insertWidget(pos, row)
            row.update_from(item)
        active = sum(1 for i in self.mgr.items if i["state"] == "progress")
        self.count.setText(f"{active} active" if active else f"{len(self.mgr.items)} this session")
        self.empty.setVisible(not items)
        self.adjustSize()
