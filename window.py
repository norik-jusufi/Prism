"""PRISM main window: tabs, split panes, the HTML toolbar and panel, search
fallback, permissions, page events and the new-tab dashboard.

Containers live in containers.py and the developer views in devtools.py;
both are mixed into PrismWindow. Imports Qt WebEngine: only import this
after prism.py has set the Chromium flags.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from urllib.parse import urlencode

from PyQt6.QtCore import QFile, QIODevice, Qt, QTimer, QUrl
from PyQt6.QtGui import QCursor, QIcon, QKeySequence, QShortcut
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QSplitter, QVBoxLayout, QWidget

from adblock import Blocklist, PrivacyEngine
from apitester import ApiTester
from bridge import Bridge
from containers import CONTAINER_PRESETS, SANDBOX_COLOR, TEMP_COLOR, USER_AGENT, Container, ContainersMixin
from devtools import DevDock, DevToolsMixin
from downloads import Downloads
from edition import EDITION, enabled
from siteintel import HeaderFetcher, site_of, trust_score
from stats import SAVE_EVERY as STATS_SAVE_EVERY
from storage import PERMISSION_TYPES, DevBookmarks, Settings
from tabs import APP_WORLD, Tab
from theme import APP_QSS, BG_DARK, BG_LIGHT, dot_icon, icon_to_data_url, set_dark_titlebar
from updates import UpdateChecker
from urls import (
    CHROME_URL, FALLBACK_NAME, ICON, LIBRE_ERROR_JS, LIBRE_RETRY_SECONDS, NEWTAB_URL, PANEL_URL, SEARCH_NAME,
    WARNING_URL, fallback_url, is_libre_search, is_local_ui, is_newtab, query_of, resolve_input,
    search_url,
)
from workspace import DEVICES, MAX_PANES, Pane


class PrismWindow(ContainersMixin, DevToolsMixin, QMainWindow):
    def __init__(self, app: QApplication, chrome_profile: QWebEngineProfile,
                 engine: PrivacyEngine, blocklist: Blocklist, settings: Settings, doh=None):
        super().__init__()
        self.app = app
        self.engine = engine
        self.interceptor = engine          # dashboard + state code read stats / counts from here
        self.blocklist = blocklist
        self.settings = settings
        self.doh = doh                     # running DohProxy, or None when encrypted DNS is off
        self.chrome_profile = chrome_profile
        self.containers: dict[str, Container] = {}
        self.refused: deque = deque(maxlen=5000)
        self._temp_n = 0
        self.tabs: list[Tab] = []
        self.active: Tab | None = None
        self.closed: list[tuple[QUrl, str]] = []   # memory only, for Ctrl+Shift+T
        self.libre_down_until = 0.0          # LibreSearch failing -> use fallback
        self.find_open = False
        self.dirty: set[int] = set()
        self._prompt_n = 0
        self._ticks = 0
        self.dev: DevDock | None = None
        self.dev_where = "bottom"
        self.pre_fullscreen_maximized = False

        # Features the partner edition leaves out are never created (see edition.py).
        self.vault = self.terminal = None
        if enabled("vault"):
            from vault import Vault
            self.vault = Vault()
        if enabled("terminal"):
            from terminal import TerminalSession
            self.terminal = TerminalSession(settings["terminal"].get("cwd", ""),
                                            settings["terminal"].get("shell", "cmd"), self)
        self.bookmarks = DevBookmarks()
        from designai import DesignAssistant
        self.design = DesignAssistant(self)
        self.api = ApiTester(self)
        self.downloads = Downloads(self)
        self.headers = HeaderFetcher(USER_AGENT, self)
        self.headers.done.connect(self.on_headers)
        self.updates = UpdateChecker(self)
        self.updates.changed.connect(self.on_updates_changed)
        # The silent installer is running: get out of its way (it restarts PRISM).
        self.updates.quit_for_update.connect(lambda: QTimer.singleShot(400, QApplication.instance().quit))
        self._update_notes_shown: set[str] = set()

        self.setWindowTitle("PRISM")
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1440, 900)
        self.setStyleSheet(APP_QSS)

        # --- HTML chrome (tabs + toolbar)
        self.chrome = QWebEngineView()
        chrome_page = QWebEnginePage(chrome_profile, self.chrome)
        chrome_page.setBackgroundColor(BG_DARK)
        self.chrome.setPage(chrome_page)
        self.chrome.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.chrome.setFixedHeight(92)
        self._inject_webchannel_js(chrome_page)
        self.bridge = Bridge(self)
        self.channel = QWebChannel(chrome_page)
        self.channel.registerObject("bridge", self.bridge)
        chrome_page.setWebChannel(self.channel)
        self.chrome.setUrl(CHROME_URL)

        # --- workspace: [panes | devtools] | panel
        self.parking = QWidget()                # holds tabs that are not on screen
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.addWidget(self.split)
        self.vsplit.setChildrenCollapsible(False)
        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setChildrenCollapsible(False)
        self.panes: list[Pane] = []
        self.pane: Pane = self._add_pane()

        # --- PRISM panel (tools)
        from panel import PanelBridge
        self.panel_view = QWebEngineView()
        panel_page = QWebEnginePage(chrome_profile, self.panel_view)
        panel_page.setBackgroundColor(BG_DARK)
        self.panel_view.setPage(panel_page)
        self.panel_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._inject_webchannel_js(panel_page)
        self.panel = PanelBridge(self)
        self.panel_channel = QWebChannel(panel_page)
        self.panel_channel.registerObject("prism", self.panel)
        panel_page.setWebChannel(self.panel_channel)
        self.panel_view.setUrl(PANEL_URL)
        self.panel_view.setMinimumWidth(380)
        self.hsplit.addWidget(self.panel_view)
        self.panel_view.hide()
        self.design.changed.connect(lambda: self.panel.push_section("design"))
        self.downloads.changed.connect(lambda: self.panel.push_section("downloads", force=False))

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.chrome)
        lay.addWidget(self.hsplit, 1)
        self.setCentralWidget(central)

        self._state_timer = QTimer(self, singleShot=True, interval=40)
        self._state_timer.timeout.connect(self.emit_state)
        self._dash_timer = QTimer(self, interval=1000)
        self._dash_timer.timeout.connect(self.tick)
        self._dash_timer.start()

        self.app.focusChanged.connect(self.on_focus_changed)
        self.install_cosmetics()
        self._shortcuts()
        self._clean_login_folders()
        self.new_tab(NEWTAB_URL)

    # ---------------------------------------------------------------- setup
    @staticmethod
    def _inject_webchannel_js(page: QWebEnginePage) -> None:
        f = QFile(":/qtwebchannel/qwebchannel.js")
        if not f.open(QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError("qwebchannel.js not found in Qt resources")
        src = bytes(f.readAll()).decode("utf-8")
        f.close()
        script = QWebEngineScript()
        script.setName("qwebchannel")
        script.setSourceCode(src)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        page.scripts().insert(script)

    def _shortcuts(self):
        def sc(keys, fn):
            for k in keys if isinstance(keys, (list, tuple)) else [keys]:
                s = QShortcut(QKeySequence(k), self)
                s.setContext(Qt.ShortcutContext.ApplicationShortcut)
                s.activated.connect(fn)

        sc("Ctrl+T", lambda: self.new_tab(NEWTAB_URL, focus_address=True, container=self.current().container))
        sc("Ctrl+Shift+N", self.new_temp_session)
        sc("Ctrl+W", lambda: self.close_tab(self.current().id))
        sc("Ctrl+Shift+T", self.reopen_closed)
        sc(["Ctrl+L", "F6", "Alt+D"], self.focus_address)
        sc("Ctrl+K", self.focus_search)
        sc(["Ctrl+R", "F5"], lambda: self.current().view.reload())
        sc("Alt+Left", lambda: self.current().view.back())
        sc("Alt+Right", lambda: self.current().view.forward())
        sc("Alt+Home", lambda: self.current().view.setUrl(NEWTAB_URL))
        sc("Ctrl+Tab", lambda: self.cycle(1))
        sc("Ctrl+Shift+Tab", lambda: self.cycle(-1))
        sc("Ctrl+F", self.open_find)
        sc(["F12", "Ctrl+Shift+I"], self.toggle_devtools)
        sc("Ctrl+Shift+C", self.toggle_inspector)
        sc("Ctrl+Shift+M", self.toggle_responsive)
        sc("Ctrl+\\", self.open_split)
        sc("Ctrl+B", lambda: self.toggle_panel(None))
        if self.terminal:
            sc("Ctrl+`", lambda: self.toggle_panel("terminal", force=True, focus=True))
        sc("Ctrl+Shift+A", lambda: self.toggle_panel("api", force=True, focus=True))
        sc("Ctrl+Shift+S", lambda: self.toggle_panel("site", force=True))
        sc("Ctrl+Shift+D", lambda: self.toggle_panel("design", force=True))
        sc("Ctrl+J", lambda: self.toggle_panel("downloads"))
        sc("Ctrl+O", self.open_files)
        sc("F11", self.toggle_fullscreen)
        sc(["Ctrl+=", "Ctrl++"], lambda: self.zoom(+0.1))
        sc("Ctrl+-", lambda: self.zoom(-0.1))
        sc("Ctrl+0", lambda: self.zoom(0))
        sc("Ctrl+Shift+Delete", self.purge)
        for i in range(1, 10):
            sc(f"Ctrl+{i}", lambda i=i: self.switch_index(i - 1 if i < 9 else -1))

    # ----------------------------------------------------------------- panes
    def _add_pane(self, index: int | None = None) -> Pane:
        pane = Pane(self)
        if index is None:
            self.split.addWidget(pane)
            self.panes.append(pane)
        else:
            self.split.insertWidget(index, pane)
            self.panes.insert(index, pane)
        return pane

    def pane_of(self, tab: Tab) -> Pane | None:
        return next((p for p in self.panes if p.tab is tab), None)

    def park(self, tab: Tab):
        tab.view.setParent(self.parking)

    def refresh_panes(self):
        split = len(self.panes) > 1
        for p in self.panes:
            p.update_header(split, p is self.pane)

    def open_split(self, url: QUrl | None = None):
        """Ctrl+\\: add a pane next to the focused one (max 4)."""
        if len(self.panes) >= MAX_PANES:
            self.bridge.toast.emit(f"Split view holds up to {MAX_PANES} panes")
            return
        idx = self.panes.index(self.pane) + 1
        pane = self._add_pane(idx)
        sizes = [1] * len(self.panes)
        self.split.setSizes([10000 // len(sizes)] * len(sizes))
        self.pane = pane
        tab = self.new_tab(url if url is not None else NEWTAB_URL, container=self.current().container,
                           focus_address=url is None)
        if pane.tab is not tab:
            pane.show_tab(tab)
        self.refresh_panes()
        self.push_state()

    def close_pane(self, pane: Pane):
        if len(self.panes) <= 1:
            return
        pane.release()
        self.panes.remove(pane)
        pane.setParent(None)
        pane.deleteLater()
        if self.pane is pane:
            self.pane = self.panes[0]
        self.active = self.pane.tab
        self.refresh_panes()
        self.update_title()
        self.push_state()

    def show_in_split(self, tab: Tab):
        if len(self.panes) >= MAX_PANES:
            self.pane.show_tab(tab)
        else:
            pane = self._add_pane(self.panes.index(self.pane) + 1)
            self.split.setSizes([10000 // len(self.panes)] * len(self.panes))
            pane.show_tab(tab)
            self.pane = pane
        self.switch_tab(tab.id)

    def on_focus_changed(self, _old, new):
        w = new
        while w is not None and not isinstance(w, Pane):
            w = w.parentWidget()
        if isinstance(w, Pane) and w is not self.pane and w.tab:
            self.pane = w
            self.active = w.tab
            self.refresh_panes()
            self.update_title()
            self.on_active_changed()
            self.push_state()

    # ----------------------------------------------------------------- tabs
    def current(self) -> Tab:
        return self.active

    def tab_by_id(self, tab_id: int) -> Tab | None:
        return next((t for t in self.tabs if t.id == tab_id), None)

    def new_tab(self, url: QUrl | None = NEWTAB_URL, activate=True, focus_address=False,
                container: Container | None = None) -> Tab:
        if container is None:
            # Follow the active tab's container, but never leak into a sandbox:
            # only links opened from a sandbox page (createWindow) stay in it.
            active = self.active.container if self.active else None
            container = active if active and active.kind != "sandbox" else self.container("default")
        tab = Tab(self, container)
        idx = self.tabs.index(self.active) + 1 if self.active in self.tabs else len(self.tabs)
        self.tabs.insert(idx, tab)
        self.park(tab)

        page = tab.page
        page.titleChanged.connect(lambda _t, tab=tab: self.on_tab_changed(tab))
        page.urlChanged.connect(lambda u, tab=tab: self.on_url_changed(tab, u))
        page.iconChanged.connect(lambda ic, tab=tab: self.on_icon(tab, ic))
        page.loadStarted.connect(lambda tab=tab: self.on_load(tab, True, 0))
        page.loadProgress.connect(lambda p, tab=tab: self.on_load(tab, True, p))
        page.loadFinished.connect(lambda ok, tab=tab: self.on_load_finished(tab, ok))
        page.findTextFinished.connect(lambda r, tab=tab: self.on_find_result(tab, r))
        page.fullScreenRequested.connect(self.on_fullscreen_request)
        page.windowCloseRequested.connect(lambda tab=tab: self.close_tab(tab.id))
        page.renderProcessTerminated.connect(lambda status, code, tab=tab: self.on_crash(tab, status, code))

        if url is not None:
            tab.view.setUrl(url)
        if activate or self.active is None:
            self.switch_tab(tab.id)
            if focus_address:
                self.focus_search()
        self.push_state()
        return tab

    def open_external(self, urls: list[str], replace_current: bool = False):
        """Links from other apps (see instance.py): open each in a new tab in the
        default container, then bring the window to the front. No links: PRISM
        was just started again, so only come to the front."""
        for i, u in enumerate(urls):
            if i == 0 and replace_current and self.active is not None:
                self.active.view.setUrl(QUrl(u))
            else:
                self.new_tab(QUrl(u), container=self.container("default"))
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def close_tab(self, tab_id: int):
        tab = self.tab_by_id(tab_id)
        if not tab:
            return
        if not is_newtab(tab.url) and tab.container.kind == "standard":
            self.closed.append((tab.url, tab.container.id))
            self.closed = self.closed[-25:]
        idx = self.tabs.index(tab)
        self.tabs.remove(tab)
        pane = self.pane_of(tab)
        if pane is not None:
            pane.release()
            # fill the pane with a tab that is not on screen yet
            spare = next((t for t in reversed(self.tabs[:idx]) if self.pane_of(t) is None), None) \
                or next((t for t in self.tabs if self.pane_of(t) is None), None)
            if spare:
                pane.show_tab(spare)
            elif len(self.panes) > 1:
                self.panes.remove(pane)
                pane.setParent(None)
                pane.deleteLater()
                if self.pane is pane:
                    self.pane = self.panes[0]
        if not self.tabs:
            self.active = None
            self.new_tab(NEWTAB_URL)
        elif tab is self.active:
            self.active = None
            self.switch_tab((self.pane.tab or self.tabs[min(idx, len(self.tabs) - 1)]).id)
        if self.dev and self.dev.view.page().inspectedPage() is tab.page:
            self.dev.view.page().setInspectedPage(None)
        tab.view.deleteLater()
        self.drop_container_if_empty(tab.container)
        self.refresh_panes()
        self.push_state()

    def reopen_closed(self):
        if self.closed:
            url, cid = self.closed.pop()
            self.new_tab(url, container=self.container(cid))

    def switch_tab(self, tab_id: int):
        tab = self.tab_by_id(tab_id)
        if not tab:
            return
        pane = self.pane_of(tab)
        if pane is None:
            self.pane.show_tab(tab)
        else:
            self.pane = pane
        if tab.discarded:
            tab.page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            tab.discarded = False
        self.active = tab
        tab.view.setFocus()
        if self.find_open:
            self.close_find()
        self.refresh_panes()
        self.update_title()
        self.on_active_changed()
        self.push_state()

    def on_active_changed(self):
        if self.dev and self.dev.isVisible():
            self.dev.view.page().setInspectedPage(self.active.page)
            self.dev.label.setText(f"DevTools · {self.active.title()}")
        self.panel.on_active_changed()

    def switch_index(self, i: int):
        """Ctrl+1..8 jump to that tab, Ctrl+9 jumps to the last one."""
        if i < 0:
            self.switch_tab(self.tabs[-1].id)
        elif i < len(self.tabs):
            self.switch_tab(self.tabs[i].id)

    def cycle(self, step: int):
        if self.tabs:
            i = (self.tabs.index(self.active) + step) % len(self.tabs)
            self.switch_tab(self.tabs[i].id)

    def navigate(self, text: str):
        tab = self.current()
        tab.view.setUrl(resolve_input(text, self.search_for))
        tab.view.setFocus()

    def discard_tab(self, tab: Tab):
        if self.pane_of(tab) is not None:
            self.bridge.toast.emit("Can't discard a tab that is on screen")
            return
        tab.page.setLifecycleState(QWebEnginePage.LifecycleState.Discarded)
        tab.discarded = True
        self.bridge.toast.emit(f"Discarded {tab.title()}: it reloads when you open it")
        self.push_state()

    # ---------------------------------------------------------------- menus
    def new_tab_menu(self):
        menu = QMenu(self)
        for cid, name, color in CONTAINER_PRESETS:
            menu.addAction(dot_icon(color), f"New {name} tab",
                           lambda c=cid: self.new_tab(NEWTAB_URL, focus_address=True, container=self.container(c)))
        menu.addSeparator()
        menu.addAction(dot_icon(TEMP_COLOR), "New temporary session\tCtrl+Shift+N", self.new_temp_session)
        menu.addAction(dot_icon(SANDBOX_COLOR), "New sandbox tab", lambda: self.open_sandbox(NEWTAB_URL))
        menu.addSeparator()
        menu.addAction("Split view\tCtrl+\\", self.open_split)
        menu.exec(QCursor.pos())

    def container_menu(self):
        t = self.current()
        menu = QMenu(self)
        menu.addSection(f"This tab: {t.container.name}")
        for cid, name, color in CONTAINER_PRESETS:
            if cid != t.container.id:
                menu.addAction(dot_icon(color), f"Reopen in {name}", lambda c=cid: self.move_to_container(t, c))
        menu.addAction(dot_icon(SANDBOX_COLOR), "Reopen in sandbox", lambda: self.open_sandbox(t.url))
        menu.addSeparator()
        menu.addAction("Manage containers…", lambda: self.toggle_panel("containers", force=True))
        menu.exec(QCursor.pos())

    def tab_menu(self, tab_id: int):
        t = self.tab_by_id(tab_id)
        if not t:
            return
        menu = QMenu(self)
        if self.pane_of(t) is None:
            menu.addAction("Show in split view", lambda: self.show_in_split(t))
        menu.addAction("Duplicate tab", lambda: self.new_tab(t.url, container=t.container))
        menu.addAction("Responsive preview\tCtrl+Shift+M", lambda: (self.switch_tab(t.id), self.toggle_responsive()))
        sub = menu.addMenu("Reopen in container")
        for cid, name, color in CONTAINER_PRESETS:
            if cid != t.container.id:
                sub.addAction(dot_icon(color), name, lambda c=cid: self.move_to_container(t, c))
        menu.addAction(dot_icon(SANDBOX_COLOR), "Reopen in sandbox", lambda: self.open_sandbox(t.url))
        if self.pane_of(t) is None and not t.discarded:
            menu.addAction("Free memory (discard tab)", lambda: self.discard_tab(t))
        menu.addSeparator()
        menu.addAction("Close tab\tCtrl+W", lambda: self.close_tab(t.id))
        menu.addAction("Close other tabs", lambda: [self.close_tab(x.id) for x in list(self.tabs) if x is not t])
        menu.exec(QCursor.pos())

    # ------------------------------------------------- search + fallback
    def libre_down(self) -> bool:
        return time.time() < self.libre_down_until

    def search_for(self, query: str) -> QUrl:
        """LibreSearch normally; DuckDuckGo while LibreSearch is known to be failing."""
        return fallback_url(query) if self.libre_down() else search_url(query)

    def check_libre(self, tab: Tab):
        url = tab.url
        if tab not in self.tabs or not is_libre_search(url):
            return
        tab.page.runJavaScript(
            LIBRE_ERROR_JS, APP_WORLD,
            lambda bad, tab=tab, url=url: self.on_libre_checked(tab, url, bool(bad)))

    def on_libre_checked(self, tab: Tab, url: QUrl, bad: bool):
        if tab not in self.tabs or tab.url != url:
            return
        if not bad:
            if not tab.loading:
                self.libre_down_until = 0.0     # LibreSearch answered: it's back
            return
        self.reroute_search(tab, url)

    def reroute_search(self, tab: Tab, url: QUrl):
        key = url.toString()
        query = query_of(url)
        if not query or tab.fallback_from == key:
            return
        tab.fallback_from = key
        self.libre_down_until = time.time() + LIBRE_RETRY_SECONDS
        stats = self.engine.stats
        stats.fallbacks += 1
        stats.searches = max(0, stats.searches - 1)   # the DuckDuckGo hit counts instead
        target = bytes(fallback_url(query).toEncoded()).decode("ascii")
        # location.replace drops the error page from history, so Back doesn't loop.
        tab.page.runJavaScript(f"location.replace({json.dumps(target)})", APP_WORLD)
        self.bridge.toast.emit(f"{SEARCH_NAME} unavailable: showing {FALLBACK_NAME} results")
        self.push_dashboards()

    # ------------------------------------------------- per-page rules
    def apply_page_rules(self, tab: Tab, url: QUrl):
        """Settings for the page about to load in this tab: JavaScript per the
        site's script rules, and local file access only for PRISM's own pages."""
        s = tab.page.settings()
        A = QWebEngineSettings.WebAttribute
        local = is_local_ui(url)
        # The new-tab and warning pages load their CSS / images from ./ui. A file
        # opened from disk gets file access too, so a saved page shows with its
        # images and styles; the request filter keeps it to the page's own
        # folder and blocks reading files from script (adblock.local_file_allowed).
        # Sandbox tabs: never.
        own_file = url.isLocalFile() and tab.container.kind != "sandbox"
        s.setAttribute(A.LocalContentCanAccessFileUrls, local or own_file)
        if local or url.scheme() in ("data", "about", "qrc", "chrome", "devtools"):
            js = True
        elif tab.container.kind == "sandbox":
            js = tab.sandbox_js
        else:
            js = self.settings.scripts_for(site_of(url.host()))["js"]
        s.setAttribute(A.JavascriptEnabled, js)
        tab.js_enabled = js

    def toggle_sandbox_js(self):
        t = self.current()
        if t.container.kind != "sandbox":
            return
        t.sandbox_js = not t.sandbox_js
        t.view.reload()
        self.bridge.toast.emit("Scripts allowed in this sandbox tab" if t.sandbox_js else "Scripts blocked again")

    # ----------------------------------------------------------- protection
    def on_blocked(self, container: str, first_party: str, host: str, url: str, rtype: str, reason: str):
        fsite = site_of(first_party)
        for t in self.tabs:
            if t.container.id != container:
                continue
            if reason == "malware" and rtype == "document":
                if t.pending_url == url or (not t.pending_url and site_of(t.url.host()) == fsite):
                    QTimer.singleShot(0, lambda t=t, u=url, h=host: self.show_warning(t, u, h))
                    t.pending_url = ""
                    return
                continue
            if site_of(t.url.host()) == fsite or site_of(QUrl(t.pending_url).host()) == fsite:
                t.log.add(url, host, rtype, first_party or host, blocked=reason)
                self.mark_dirty(t)
        self.push_state()

    def show_warning(self, tab: Tab, url: str, host: str):
        q = urlencode({"u": url, "h": host})
        tab.view.setUrl(QUrl(WARNING_URL.toString() + "?" + q))

    def proceed_anyway(self, tab: Tab, target: str):
        host = QUrl(target).host().lower()
        if not host:
            return
        self.engine.malware_allow.add(host)
        self.bridge.toast.emit(f"Allowed {host} for this session. Be careful what you enter there.")
        tab.view.setUrl(QUrl(target))

    # ---------------------------------------------------------- permissions
    def on_permission(self, tab: Tab, perm):
        ptype = perm.permissionType().name
        origin = perm.origin()
        site = site_of(origin.host()) or origin.toString()
        if tab.container.kind == "sandbox" or ptype not in PERMISSION_TYPES:
            perm.deny()
            self.engine.stats.perms_denied += 1
            return
        policy = self.settings.permission_policy(site, ptype)
        if policy == "allow":
            perm.grant()
            return
        if policy == "block":
            perm.deny()
            self.engine.stats.perms_denied += 1
            return
        if any(p["site"] == site and p["type"] == ptype for p in tab.prompts):
            return
        self._prompt_n += 1
        tab.prompts.append({"id": f"p{self._prompt_n}", "site": site, "type": ptype,
                            "label": PERMISSION_TYPES[ptype][0], "_perm": perm})
        if tab is not self.active:
            self.bridge.toast.emit(f"{site} (in another tab) is asking for {PERMISSION_TYPES[ptype][0].lower()}")
        self.push_state()
        self.panel.push_section("permissions")

    def answer_permission(self, prompt_id: str, allow: bool, remember: bool):
        for t in self.tabs:
            for p in list(t.prompts):
                if p["id"] != prompt_id:
                    continue
                t.prompts.remove(p)
                perm = p["_perm"]
                if allow:
                    perm.grant()
                else:
                    perm.deny()
                    self.engine.stats.perms_denied += 1
                if remember:
                    self.settings.set_site_permission(p["site"], p["type"], "allow" if allow else "block")
                self.push_state()
                self.panel.push_section("permissions")
                return

    def present_notification(self, notification):
        origin = notification.origin().host()
        self.bridge.toast.emit(f"{origin}: {notification.title()} {notification.message()}".strip())

    # --------------------------------------------------------- page events
    def on_tab_changed(self, tab: Tab):
        if tab is self.active:
            self.update_title()
        pane = self.pane_of(tab)
        if pane:
            pane.update_header()
        self.push_state()

    def on_url_changed(self, tab: Tab, url: QUrl):
        tab.page.setBackgroundColor(BG_DARK if is_local_ui(url) else BG_LIGHT)
        if is_newtab(url):
            tab.icon = ""
        tab.inspector = False
        if is_libre_search(url):
            # LibreSearch can also navigate client-side (no loadFinished), so poll briefly.
            for delay in (1200, 3000, 6000):
                QTimer.singleShot(delay, lambda tab=tab: self.check_libre(tab))
        self.on_tab_changed(tab)

    def on_icon(self, tab: Tab, icon: QIcon):
        tab.icon = icon_to_data_url(icon)
        self.push_state()

    def on_load(self, tab: Tab, loading: bool, progress: int):
        tab.loading, tab.progress = loading, progress
        self.push_state()

    def on_load_finished(self, tab: Tab, ok: bool):
        tab.loading, tab.progress = False, 100
        url = tab.url
        if is_libre_search(url):
            if ok:
                self.check_libre(tab)
            else:                                   # LibreSearch unreachable entirely
                self.reroute_search(tab, url)
        if is_newtab(url):
            tab._dash_last = None      # fresh page: send everything
            self.push_dashboard(tab)
        if ok and url.scheme() in ("http", "https"):
            self.headers.fetch(url.toString(QUrl.UrlFormattingOption.RemoveFragment))
        self.mark_dirty(tab)
        self.push_state()

    def on_headers(self, url: str, result: dict):
        for t in self.tabs:
            if t.url.toString(QUrl.UrlFormattingOption.RemoveFragment) == url:
                t.headers = result
                if result.get("certError"):
                    t.cert_error = t.cert_error or result["certError"]
                self.mark_dirty(t)
        self.push_state()

    def on_crash(self, tab: Tab, status, code):
        if status != QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
            self.bridge.toast.emit(f"{tab.title()} crashed (code {code}). Reload to try again.")

    def mark_dirty(self, tab: Tab):
        self.dirty.add(tab.id)

    def trust_for(self, tab: Tab) -> dict | None:
        url = tab.url
        if url.scheme() not in ("http", "https"):
            return None
        key = (len(tab.log.entries), len(tab.log.cookies_refused), id(tab.headers),
               len(tab.container.cookies), tab.cert_error)
        cached = getattr(tab, "_trust", None)
        now = time.monotonic()
        # While a page loads its log grows on every request; rescoring it on
        # every state push wastes the UI thread, so refresh twice a second.
        if cached and (cached[0] == key or (tab.loading and now - cached[2] < 0.5)):
            return cached[1]
        result = trust_score(url=url.toString(), log=tab.log, cookies=self.site_cookies(tab), headers=tab.headers,
                             malicious=self.blocklist.is_malicious(url.host()), cert_error=tab.cert_error,
                             tracker_check=self.engine.is_tracker)
        tab._trust = (key, result, now)
        return result

    # ------------------------------------------------------------ dashboard
    def dashboard_data(self) -> str:
        data = self.engine.stats.snapshot()
        data.update(rules=len(self.blocklist), sources=self.blocklist.sources,
                    tabs=len(self.tabs), shieldOff=len(self.engine.site_allow),
                    engine={"primary": SEARCH_NAME, "fallback": FALLBACK_NAME,
                            "down": self.libre_down(),
                            "retryIn": max(0, int(self.libre_down_until - time.time()))},
                    edition=EDITION, updates=self.updates.snapshot())
        return json.dumps(data)

    def push_dashboard(self, tab: Tab, data: str | None = None):
        """Send stats to one dashboard.

        Skips the call entirely when the tab already shows this data, so an
        idle dashboard costs nothing."""
        data = data or self.dashboard_data()
        if getattr(tab, "_dash_last", None) != data:
            tab._dash_last = data
            tab.page.runJavaScript(f"window.prismStats && window.prismStats({data})")

    def push_dashboards(self):
        """Live-update the dashboards that are on screen, once a second.

        New-tab pages parked in the background get fresh data as soon as they
        are shown again (next tick), not every second while hidden."""
        if self.isMinimized():
            return
        tabs = [t for t in self.tabs if is_newtab(t.url) and not t.loading and self.pane_of(t) is not None]
        if tabs:
            data = self.dashboard_data()
            for t in tabs:
                self.push_dashboard(t, data)

    def install_update(self):
        """"Install update" on the dashboard (installed Windows copies)."""
        self.bridge.toast.emit(self.updates.install_update())
        self.push_dashboards()

    def on_updates_changed(self):
        inst = self.updates.install
        if inst.get("status") == "error" and inst is not getattr(self, "_update_err_shown", None):
            self._update_err_shown = inst
            self.bridge.toast.emit(f"Update failed: {inst['error']}")
        for note in self.updates.snapshot()["notes"]:
            if note["text"] not in self._update_notes_shown:
                self._update_notes_shown.add(note["text"])
                self.bridge.toast.emit(note["text"])
        self.push_dashboards()

    def tick(self):
        self.drain_refused()
        self._ticks += 1
        if self._ticks % STATS_SAVE_EVERY == 0:
            self.engine.stats.save()
        self.push_dashboards()
        if self.vault and self.vault.expired():
            self.vault.lock()
            self.panel.push_section("vault")
        self.panel.tick()
        t = self.current()
        if t and t.inspector:      # the page's own Esc can switch the inspector off
            t.page.runJavaScript("!!(window.__prismInspect && window.__prismInspect.isOn())", APP_WORLD,
                                 lambda on, t=t: on is False and self._inspector_state(t, False))
        if self.dirty:
            self.push_state()

    def update_title(self):
        t = self.current()
        self.setWindowTitle(f"{t.title()} · PRISM" if t and not is_newtab(t.url) else "PRISM")

    # -------------------------------------------------------------- state
    def push_state(self):
        if not self._state_timer.isActive():
            self._state_timer.start()

    def emit_state(self):
        if not self.active:
            return
        t = self.active
        url = t.url
        host = url.host().lower()
        newtab = is_newtab(url)
        local = is_local_ui(url)
        trust = None if local else self.trust_for(t)
        prompt = next(({k: v for k, v in p.items() if k != "_perm"} for p in t.prompts), None)
        state = {
            "tabs": [{
                "id": x.id, "title": x.title(), "icon": x.icon,
                "loading": x.loading, "active": x is t,
                "newtab": is_newtab(x.url), "shown": self.pane_of(x) is not None,
                "container": x.container.info(), "discarded": x.discarded,
                "asking": bool(x.prompts),
            } for x in self.tabs],
            "url": "" if newtab else url.toString(),
            "host": "" if local else host,
            "scheme": url.scheme(),
            "newtab": newtab,
            "local": local,
            "secure": url.scheme() == "https",
            "canBack": t.view.history().canGoBack(),
            "canForward": t.view.history().canGoForward(),
            "loading": t.loading,
            "progress": t.progress,
            "blocked": 0 if local else self.engine.counts.get(host, 0),
            "total": self.engine.total,
            "shieldOn": not self.engine.shield_off_for(host),
            "zoom": round(t.view.zoomFactor() * 100) if not t.device else round(t.user_zoom * 100),
            "find": {"open": self.find_open, **t.find},
            "rules": len(self.blocklist),
            "requests": self.engine.stats.requests,
            "container": t.container.info(),
            "jsOff": not getattr(t, "js_enabled", True) and not local,
            "trust": {"score": trust["score"], "grade": trust["grade"]} if trust else None,
            "prompt": prompt,
            "device": t.device,
            "devices": [{"name": n, "w": w, "h": h} for n, w, h in DEVICES],
            "panes": len(self.panes),
            "panel": self.panel_view.isVisible(),
            "panelSection": self.panel.section,
            "inspector": t.inspector,
            "devtools": bool(self.dev and self.dev.isVisible()),
            "dns": self.settings["dns"]["mode"] if self.doh else "off",
        }
        self.dirty.discard(t.id)
        self.bridge.stateChanged.emit(json.dumps(state))

    # ------------------------------------------------------------ actions
    def focus_address(self):
        self.chrome.setFocus()
        self.chrome.page().runJavaScript("window.focusAddress && focusAddress()")

    def focus_search(self):
        """Ctrl+K: on the new-tab page focus its search box, else the address bar."""
        t = self.current()
        if t and is_newtab(t.url) and not t.loading:
            t.view.setFocus()
            t.page.runJavaScript("window.focusSearch && focusSearch()")
        else:
            self.focus_address()

    def toggle_shield(self):
        host = self.current().url.host().lower()
        if not host:
            return
        allow = self.engine.site_allow
        if host in allow:
            allow.discard(host)
            self.bridge.toast.emit(f"shield ON for {host}")
        else:
            allow.add(host)
            self.bridge.toast.emit(f"shield OFF for {host} (this session)")
        self.install_cosmetics()
        self.current().view.reload()
        self.push_state()

    def purge(self):
        """Wipe the whole session: tabs, cookies, cache, storage, history."""
        for pane in self.panes[1:]:
            pane.release()
            pane.setParent(None)
            pane.deleteLater()
        self.panes = self.panes[:1]
        self.pane = self.panes[0]
        self.pane.release()
        for tab in list(self.tabs):
            tab.view.deleteLater()
        self.tabs.clear()
        self.active = None
        self.closed.clear()
        kept = []
        for c in list(self.containers.values()):
            if c.login_dir is not None:          # opted in: keep its logins, drop the rest
                c.profile.clearHttpCache()
                c.profile.clearAllVisitedLinks()
                kept.append(c.name)
            elif c.kind == "standard":
                self.clear_container(c)
            else:
                self.drop_container_if_empty(c)
        self.engine.counts.clear()
        self.engine.stats.wipe()
        self.engine.site_allow.clear()
        self.engine.malware_allow.clear()
        self.headers.cache.clear()
        self.install_cosmetics()
        self.new_tab(NEWTAB_URL, container=self.container("default"))
        self.refresh_panes()
        self.bridge.toast.emit("session purged: cookies, cache, history wiped"
                               + (f" (saved logins kept in {', '.join(kept)})" if kept else ""))

    def toggle_panel(self, section: str | None, force: bool = False, focus: bool = False):
        visible = self.panel_view.isVisible()
        if visible and not force and (section is None or section == self.panel.section):
            self.panel_view.hide()
            self.current().view.setFocus()
        else:
            if not visible:
                self.panel_view.show()
                total = self.hsplit.width()
                sizes = self.hsplit.sizes()
                want = max(420, min(560, total // 3))
                sizes[-1] = want
                sizes[0] = max(300, total - sum(sizes[1:-1]) - want)
                self.hsplit.setSizes(sizes)
            self.panel.open(section or self.panel.section, focus)
            if focus:
                self.panel_view.setFocus()
        self.push_state()

    def zoom(self, delta: float):
        t = self.current()
        if t.device:
            self.bridge.toast.emit("Zoom is fixed in responsive preview")
            return
        t.user_zoom = 1.0 if delta == 0 else max(0.3, min(3.0, t.user_zoom + delta))
        t.view.setZoomFactor(t.user_zoom)
        self.bridge.toast.emit(f"zoom {round(t.user_zoom * 100)}%")
        self.push_state()

    # find in page
    def open_find(self):
        self.find_open = True
        self.chrome.setFocus()
        self.chrome.page().runJavaScript("window.openFind && openFind()")
        self.push_state()

    def find(self, text: str, backwards: bool):
        t = self.current()
        t.find["text"] = text
        flags = QWebEnginePage.FindFlag.FindBackward if backwards else QWebEnginePage.FindFlag(0)
        if not text:
            t.find.update(matches=0, active=0)
            t.page.findText("")
            self.push_state()
            return
        t.page.findText(text, flags)

    def on_find_result(self, tab: Tab, result):
        tab.find["matches"] = result.numberOfMatches()
        tab.find["active"] = result.activeMatch()
        self.push_state()

    def close_find(self):
        self.find_open = False
        t = self.current()
        if t:
            t.page.findText("")
            t.find = {"text": "", "matches": 0, "active": 0}
            t.view.setFocus()
        self.push_state()

    # fullscreen (videos) + F11
    def on_fullscreen_request(self, request):
        request.accept()
        self.set_fullscreen(request.toggleOn())

    def toggle_fullscreen(self):
        self.set_fullscreen(not self.isFullScreen())

    def set_fullscreen(self, on: bool):
        if on and not self.isFullScreen():
            self.pre_fullscreen_maximized = self.isMaximized()
            self.chrome.hide()
            self.showFullScreen()
        elif not on and self.isFullScreen():
            self.chrome.show()
            if self.pre_fullscreen_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            # If a video put the page in fullscreen, let the page know too.
            self.current().page.triggerAction(QWebEnginePage.WebAction.ExitFullScreen)

    # downloads
    def on_download(self, download, container: Container):
        if container.kind == "sandbox":
            download.cancel()
            self.bridge.toast.emit("Downloads are blocked in the sandbox")
            return
        self.downloads.handle(download)

    # local files
    OPEN_FILTER = ("Documents and pages (*.pdf *.html *.htm *.xhtml *.shtml *.mhtml *.mht *.svg *.txt *.md *.json "
                   "*.xml *.log);;Images (*.png *.jpg *.jpeg *.gif *.webp *.avif *.bmp *.ico *.svg);;"
                   "Video and audio (*.mp4 *.webm *.mp3 *.ogg *.wav);;All files (*)")

    def open_files(self):
        """Ctrl+O: open files from disk, each in a new tab."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Open in PRISM", self.settings.data.get("openDir", ""),
                                                self.OPEN_FILTER)
        if paths:
            self.settings.data["openDir"] = os.path.dirname(paths[0])
            self.settings.save()
            self.open_external([QUrl.fromLocalFile(p).toString() for p in paths])

    def showEvent(self, event):
        super().showEvent(event)
        set_dark_titlebar(self)
