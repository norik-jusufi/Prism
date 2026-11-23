"""PRISM developer views: docked Chromium DevTools, the design inspector and
the responsive preview. `DevToolsMixin` is the main window's side of them.

Imports Qt WebEngine: only import this after prism.py has set the Chromium
flags.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from tabs import APP_WORLD
from theme import BG_DARK, set_dark_titlebar
from urls import ICON, UI, is_local_ui

if TYPE_CHECKING:
    from tabs import Tab
    from window import PrismWindow

INSPECTOR_JS = (UI / "inspector.js").read_text(encoding="utf-8")

# Re-skins the Chromium DevTools frontend in PRISM's colours (see ui/devtools.css).
# Runs at document creation so DevTools never flashes its stock theme.
DEVTOOLS_THEME_JS = """(function () {
  var css = %s;
  function add() {
    var root = document.head || document.documentElement;
    if (!root) return false;
    if (!document.getElementById("prism-theme")) {
      var s = document.createElement("style");
      s.id = "prism-theme";
      s.textContent = css;
      root.appendChild(s);
    }
    return true;
  }
  if (!add()) {
    var mo = new MutationObserver(function () { if (add()) mo.disconnect(); });
    mo.observe(document, {childList: true, subtree: true});
  }
})();""" % json.dumps((UI / "devtools.css").read_text(encoding="utf-8"))


class DevDock(QWidget):
    """Docked Chromium DevTools: elements, styles, console, sources, network."""

    def __init__(self, window: "PrismWindow"):
        super().__init__()
        self.w = window
        self.setObjectName("devDock")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget(objectName="devBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 2, 0)
        bl.setSpacing(2)
        self.label = QLabel("DevTools", objectName="devTitle")
        bl.addWidget(self.label, 1)
        for text, tip, where in [("▁", "Dock to bottom", "bottom"), ("▕", "Dock to right", "right"),
                                 ("⧉", "Open in separate window", "window")]:
            b = QToolButton(objectName="devBtn", text=text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, w=where: self.w.dock_devtools(w))
            bl.addWidget(b)
        close = QToolButton(objectName="devBtn", text="✕")
        close.setToolTip("Close DevTools (F12)")
        close.clicked.connect(self.w.close_devtools)
        bl.addWidget(close)
        bar.setFixedHeight(26)
        self.view = QWebEngineView()
        self.view.page().setBackgroundColor(BG_DARK)
        theme = QWebEngineScript()
        theme.setName("prism-devtools-theme")
        theme.setSourceCode(DEVTOOLS_THEME_JS)
        theme.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        theme.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self.view.page().scripts().insert(theme)
        lay.addWidget(bar)
        lay.addWidget(self.view, 1)
        self.setWindowTitle("DevTools · PRISM")
        self.setWindowIcon(QIcon(str(ICON)))

    def closeEvent(self, event):
        if self.isWindow():
            event.ignore()
            self.w.close_devtools()
        else:
            super().closeEvent(event)


class DevToolsMixin:
    """DevTools dock, design inspector and responsive preview for PrismWindow."""

    dev: DevDock | None

    # --- devtools
    def toggle_devtools(self):
        if self.dev and self.dev.isVisible():
            self.close_devtools()
        else:
            self.open_devtools()

    def open_devtools(self):
        if self.dev is None:
            self.dev = DevDock(self)
        self.dev.view.page().setInspectedPage(self.current().page)
        self.dev.label.setText(f"DevTools · {self.current().title()}")
        self.dock_devtools(self.dev_where)
        self.push_state()

    def inspect_element(self):
        self.open_devtools()
        self.current().page.triggerAction(QWebEnginePage.WebAction.InspectElement)

    def dock_devtools(self, where: str):
        if not self.dev:
            return
        self.dev_where = where
        dev = self.dev
        if where == "window":
            dev.setParent(None)
            dev.setWindowFlag(Qt.WindowType.Window, True)
            dev.resize(1000, 700)
            dev.show()
            set_dark_titlebar(dev)
        else:
            if dev.isWindow():
                dev.setWindowFlag(Qt.WindowType.Window, False)
            if where == "right":
                self.hsplit.insertWidget(1, dev)
                total = self.hsplit.width()
                panel = self.panel_view.width() if self.panel_view.isVisible() else 0
                self.hsplit.setSizes([int((total - panel) * 0.6), int((total - panel) * 0.4), panel])
            else:
                self.vsplit.addWidget(dev)
                self.vsplit.setSizes([int(self.vsplit.height() * 0.62), int(self.vsplit.height() * 0.38)])
            dev.show()
        self.push_state()

    def close_devtools(self):
        if not self.dev:
            return
        self.dev.view.page().setInspectedPage(None)
        self.dev.hide()
        if self.dev.isWindow():
            self.dev.setWindowFlag(Qt.WindowType.Window, False)
            self.vsplit.addWidget(self.dev)
            self.dev.hide()
        self.current().view.setFocus()
        self.push_state()

    # --- design inspector
    def toggle_inspector(self):
        t = self.current()
        if not t or is_local_ui(t.url):
            self.bridge.toast.emit("Open a website to inspect its design")
            return
        t.page.runJavaScript(INSPECTOR_JS + "\n;window.__prismInspect.toggle()", APP_WORLD,
                             lambda on, t=t: self._inspector_state(t, on))

    def _inspector_state(self, tab: "Tab", on):
        tab.inspector = bool(on)
        if on:
            tab.view.setFocus()
            self.bridge.toast.emit("Design inspector: hover to inspect, click to pin, Alt for distances, Esc to exit")
        self.push_state()

    # --- responsive preview
    def toggle_responsive(self):
        t = self.current()
        if t.device:
            t.device = None
        else:
            t.device = {"name": "Mobile", "w": 390, "h": 844}
        pane = self.pane_of(t)
        if pane:
            pane.apply_device()
        self.push_state()

    def set_device(self, name: str, w: int, h: int):
        t = self.current()
        w, h = max(200, min(3840, int(w))), max(200, min(2560, int(h)))
        t.device = {"name": name or "Custom", "w": w, "h": h}
        pane = self.pane_of(t)
        if pane:
            pane.apply_device()
        self.push_state()

    def rotate_device(self):
        t = self.current()
        if t.device:
            self.set_device(t.device["name"], t.device["h"], t.device["w"])
