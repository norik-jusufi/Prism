"""PRISM tabs: one web page, its view and everything PRISM tracks about it.

Imports Qt WebEngine: only import this after prism.py has set the Chromium
flags.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView

from adblock import RequestLogger, tracking_params
from containers import CONTAINER_PRESETS, Container
from siteintel import TabLog
from theme import BG_DARK
from urls import is_newtab, is_warning

if TYPE_CHECKING:
    from window import PrismWindow

# PRISM's own scripts run in this isolated JS world, out of the page's reach.
APP_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld.value


class ContentPage(QWebEnginePage):
    def __init__(self, profile, window: "PrismWindow", tab: "Tab", parent=None):
        super().__init__(profile, parent)
        self.w = window
        self.tab = tab
        if hasattr(self, "permissionRequested"):           # Qt >= 6.8
            self.permissionRequested.connect(lambda perm: self.w.on_permission(self.tab, perm))
        else:  # older Qt: deny everything
            self.featurePermissionRequested.connect(
                lambda origin, feature: self.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser))
        if hasattr(self, "certificateError"):
            self.certificateError.connect(self._cert_error)

    def _cert_error(self, err):
        self.tab.cert_error = err.description()
        err.rejectCertificate()

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main: bool) -> bool:  # noqa: N802
        if url.host() == "prism.invalid":                  # PRISM's own pages asking PRISM to act
            if is_main and url.path() == "/update" and is_newtab(self.url()):
                QTimer.singleShot(0, self.w.install_update)   # "Install update" on the dashboard
            elif is_main and is_warning(self.url()):       # "continue anyway" on the warning page
                target = parse_qs(url.query()).get("u", [""])[0]
                if target:
                    QTimer.singleShot(0, lambda: self.w.proceed_anyway(self.tab, target))
            return False
        if is_main:
            self.tab.pending_url = url.toString()
            self.w.apply_page_rules(self.tab, url)
            removed = tracking_params(url)
            if removed:
                self.w.timemachine.stripped(self.tab, removed)
        return True

    def javaScriptConsoleMessage(self, _level, message, _line, _source):  # noqa: N802
        # Keeps the terminal quiet; only the Time Machine's watcher is listened to.
        tm = self.w.timemachine
        if message.startswith(tm.token):
            tm.on_probe(self.tab, message[len(tm.token):])


class ContentView(QWebEngineView):
    def __init__(self, window: "PrismWindow", tab: "Tab"):
        super().__init__()
        self.w = window
        self.tab = tab

    def createWindow(self, kind):  # target=_blank, "open link in new tab", ...
        background = kind == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        tab = self.w.new_tab(None, activate=not background, container=self.tab.container)
        return tab.view

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        req = self.lastContextMenuRequest()
        link = req.linkUrl() if req else QUrl()
        menu.addSeparator()
        if link.isValid() and not link.isEmpty():
            menu.addAction("Open link in split view", lambda: self.w.open_split(link))
            menu.addAction("Open link in sandbox", lambda: self.w.open_sandbox(link))
            sub = menu.addMenu("Open link in container")
            for cid, name, _ in CONTAINER_PRESETS:
                sub.addAction(name, lambda c=cid: self.w.new_tab(link, container=self.w.container(c)))
            menu.addSeparator()
        menu.addAction("Inspect design\tCtrl+Shift+C", self.w.toggle_inspector)
        menu.addAction("Inspect element (DevTools)", self.w.inspect_element)
        menu.addAction("View source in panel", lambda: self.w.toggle_panel("source", force=True))
        menu.exec(event.globalPos())


class Tab:
    _next = 1

    def __init__(self, window: "PrismWindow", container: Container):
        self.id = Tab._next
        Tab._next += 1
        self.container = container
        self.view = ContentView(window, self)
        self.page = ContentPage(container.profile, window, self, self.view)
        self.view.setPage(self.page)
        self.page.setBackgroundColor(BG_DARK)
        self.log = TabLog()
        self.logger = RequestLogger(self._on_request, self.page)
        self.page.setUrlRequestInterceptor(self.logger)
        self.icon = ""
        self.loading = False
        self.progress = 0
        self.find = {"text": "", "matches": 0, "active": 0}
        self.fallback_from = ""   # LibreSearch URL we already rerouted
        self.pending_url = ""
        self.prompts: list[dict] = []    # pending permission requests
        self.device: dict | None = None  # responsive preview {name, w, h}
        self.user_zoom = 1.0
        self.sandbox_js = False
        self.headers: dict | None = None
        self.cert_error = ""
        self.inspector = False
        self.discarded = False
        self.js_enabled = True
        self.tm_pending: list[dict] = []   # Time Machine events seen before the page's recording starts
        self.window = window

    def _on_request(self, url, host, rtype, first_party, is_main):
        tm = self.window.timemachine
        if is_main:
            self.log.reset(url)
            self.headers = None
            self.cert_error = ""
            tm.begin(self, url)
        self.log.add(url, host, rtype, first_party or host)
        tm.request(self, url, host, rtype)
        self.window.mark_dirty(self)

    @property
    def url(self) -> QUrl:
        return self.page.url()

    def title(self) -> str:
        if is_newtab(self.url):
            return "New tab"
        if is_warning(self.url):
            return "Blocked: dangerous site"
        return self.page.title() or self.url.host() or self.url.toString()
