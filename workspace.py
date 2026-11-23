"""PRISM split workspace: up to four panes, each showing one tab, optionally
at a fixed device size (responsive preview)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from tabs import Tab
    from window import PrismWindow

MAX_PANES = 4

DEVICES = [  # name, width, height (CSS px)
    ("Desktop", 1440, 900), ("Laptop", 1280, 800), ("Tablet", 768, 1024),
    ("Mobile", 390, 844), ("Small phone", 360, 640),
]


class Pane(QFrame):
    """One slot of the split workspace."""

    def __init__(self, window: "PrismWindow"):
        super().__init__()
        self.w = window
        self.tab: Tab | None = None
        self.setObjectName("pane")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QWidget(objectName="paneHeader")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(10, 0, 2, 0)
        hl.setSpacing(8)
        self.dot = QLabel(objectName="paneDot")
        self.dot.setFixedSize(8, 8)
        self.title = QLabel(objectName="paneTitle")
        self.close_btn = QToolButton(objectName="paneClose", text="✕")
        self.close_btn.setToolTip("Close this pane (the tab stays open)")
        self.close_btn.clicked.connect(lambda: self.w.close_pane(self))
        hl.addWidget(self.dot)
        hl.addWidget(self.title, 1)
        hl.addWidget(self.close_btn)
        self.header.setFixedHeight(26)
        self.stage = QWidget(objectName="stage")
        self.grid = QGridLayout(self.stage)
        self.grid.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.header)
        lay.addWidget(self.stage, 1)
        self.header.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.header and event.type() == QEvent.Type.MouseButtonPress and self.tab:
            self.w.switch_tab(self.tab.id)
        return False

    def show_tab(self, tab: "Tab"):
        if self.tab is tab:
            return
        if self.tab is not None:
            self.w.park(self.tab)
        self.tab = tab
        self.grid.addWidget(tab.view, 0, 0)
        tab.view.show()
        self.apply_device()
        self.update_header()

    def release(self) -> "Tab | None":
        tab, self.tab = self.tab, None
        if tab is not None:
            self.w.park(tab)
        return tab

    def update_header(self, split: bool | None = None, focused: bool = False):
        if split is not None:
            self.header.setVisible(split)
            self.setProperty("focused", focused and split)
            self.header.setProperty("focused", focused and split)
            for w in (self, self.header):
                w.style().unpolish(w)
                w.style().polish(w)
        if self.tab:
            self.title.setText(self.tab.title())
            self.dot.setStyleSheet(f"background:{self.tab.container.color};border-radius:4px;")

    def apply_device(self):
        tab = self.tab
        if tab is None:
            return
        view = tab.view
        if tab.device:
            margin = 24
            aw = max(100, self.stage.width() - margin * 2)
            ah = max(100, self.stage.height() - margin * 2)
            w, h = tab.device["w"], tab.device["h"]
            scale = max(0.25, min(1.0, aw / w, ah / h))
            tab.device["scale"] = round(scale, 3)
            view.setFixedSize(int(w * scale), int(h * scale))
            self.grid.setAlignment(view, Qt.AlignmentFlag.AlignCenter)
            if abs(view.zoomFactor() - scale) > 0.001:
                view.setZoomFactor(scale)
        else:
            view.setMinimumSize(0, 0)
            view.setMaximumSize(16777215, 16777215)
            self.grid.setAlignment(view, Qt.AlignmentFlag(0))
            if abs(view.zoomFactor() - tab.user_zoom) > 0.001:
                view.setZoomFactor(tab.user_zoom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.tab and self.tab.device:
            QTimer.singleShot(0, self.apply_device)
