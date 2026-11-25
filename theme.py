"""PRISM look for the Qt-native parts: colours, the widget stylesheet,
small icons and the Windows title bar."""

from __future__ import annotations

import sys

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

BG_DARK = QColor("#040a07")
BG_LIGHT = QColor("#ffffff")


def icon_to_data_url(icon: QIcon) -> str:
    if icon.isNull():
        return ""
    pm = icon.pixmap(32, 32)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return "data:image/png;base64," + bytes(data.toBase64()).decode()


def dot_icon(color: str) -> QIcon:
    pm = QPixmap(12, 12)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 8, 8)
    p.end()
    return QIcon(pm)


def set_dark_titlebar(widget: QWidget):
    """Windows 11: dark green caption bar instead of the default white one."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi

        def attr(key, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, key, ctypes.byref(v), ctypes.sizeof(v))

        attr(20, 1)              # DWMWA_USE_IMMERSIVE_DARK_MODE
        attr(35, 0x00070A04)     # DWMWA_CAPTION_COLOR  #040a07 (0x00BBGGRR)
        attr(36, 0x009BF536)     # DWMWA_TEXT_COLOR     #36f59b
        attr(34, 0x00305A1A)     # DWMWA_BORDER_COLOR   #1a5a30
    except Exception:  # noqa: BLE001 - purely cosmetic
        pass


# Qt-native widgets (menus, split panes, docks) styled to match the HTML UI.
APP_QSS = """
QMenu { background:#07110c; color:#d6f5e2; border:1px solid #1d4a32; padding:4px;
        font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:12px; }
QMenu::item { padding:6px 22px 6px 14px; border-radius:4px; }
QMenu::item:selected { background:#0f2a1c; color:#36f59b; }
QMenu::item:disabled { color:#4b6656; }
QMenu::separator { height:1px; background:#163826; margin:4px 8px; }
QMenu::section { color:#5f8270; padding:4px 14px; }
QToolTip { background:#07110c; color:#36f59b; border:1px solid #1d4a32; }
QSplitter::handle { background:#163826; }
QSplitter::handle:horizontal { width:3px; }
QSplitter::handle:vertical { height:3px; }
QSplitter::handle:hover { background:#36f59b; }
#stage { background:#020604; }
#pane[focused="true"] { border:1px solid #1fa866; }
#paneHeader { background:#07110c; border-bottom:1px solid #163826; }
#paneHeader[focused="true"] { background:#0b1a12; border-bottom:1px solid #36f59b; }
#paneTitle { color:#a9c9b5; font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:11px; }
#paneHeader[focused="true"] #paneTitle { color:#e8f5ec; }
#paneClose, #devBtn { color:#5f8270; background:transparent; border:none; padding:2px 7px;
                      font-family:'Segoe UI Symbol','Cascadia Code',monospace; font-size:12px; }
#paneClose:hover, #devBtn:hover { color:#36f59b; background:#0f2a1c; }
#devBar { background:#07110c; border-top:1px solid #1f5537; border-bottom:1px solid #163826; }
#devTitle { color:#36f59b; font-family:'Cascadia Code','Consolas','SF Mono','Menlo','DejaVu Sans Mono',monospace; font-size:11px; }
"""
