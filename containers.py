"""PRISM containers: isolated browsing identities.

Each container has its own Qt WebEngine profile, so cookies, storage and
cache never cross between them. Standard containers (Default, Work, ...)
live for the whole session; temporary sessions and sandboxes are thrown
away with their last tab. `ContainersMixin` is the part of the main window
that creates, rebuilds and clears them.

Imports Qt WebEngine: only import this after prism.py has set the Chromium
flags.
"""

from __future__ import annotations

import shutil
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWidgets import QApplication

from adblock import PrivacyEngine, PrivacyInterceptor, cosmetic_script
from siteintel import cookie_purpose, site_of
from storage import logins_dir
from urls import NEWTAB_URL, is_newtab

if TYPE_CHECKING:
    from tabs import Tab

CONTAINER_PRESETS = [
    ("default",  "Default",     "#36f59b"),
    ("work",     "Work",        "#4fd8e8"),
    ("personal", "Personal",    "#f5c84c"),
    ("banking",  "Banking",     "#ff9a5c"),
    ("dev",      "Development", "#b48cff"),
]
TEMP_COLOR = "#c9d6cf"
SANDBOX_COLOR = "#ff5f6d"


def _user_agent() -> str:
    """A common desktop UA instead of the default one, which says
    "QtWebEngine" and makes this browser trivially fingerprintable. The
    Chrome version is the Chromium PRISM really runs: a different one would
    contradict the Sec-CH-UA client hints Chromium sends anyway."""
    major = "140"
    try:
        from PyQt6.QtWebEngineCore import qWebEngineChromiumVersion
        major = qWebEngineChromiumVersion().split(".")[0] or major
    except ImportError:
        pass
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")


USER_AGENT = _user_agent()


class Container:
    """One isolated browsing identity: its own profile, cookies and storage."""

    def __init__(self, cid: str, name: str, color: str, kind: str):
        self.id, self.name, self.color, self.kind = cid, name, color, kind   # kind: standard|temp|sandbox
        self.login_dir: Path | None = None   # set => "Remember logins": cookies + storage kept on disk
        self.profile: QWebEngineProfile | None = None
        self.interceptor: PrivacyInterceptor | None = None
        self.cookies: dict[tuple, dict] = {}

    def info(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color, "kind": self.kind,
                "remember": self.login_dir is not None}


def build_content_profile(app: QApplication, engine: PrivacyEngine, container: Container,
                          refused: deque) -> QWebEngineProfile:
    if container.login_dir is None:
        profile = QWebEngineProfile(app)  # no storage name => off-the-record
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    else:
        # "Remember logins": cookies and site storage live in this container's
        # own folder. The cache stays in memory and visited links are wiped, so
        # nothing resembling history is kept. Session cookies still end with
        # the session, as in any browser.
        profile = QWebEngineProfile("prism-" + container.login_dir.name, app)
        profile.setPersistentStoragePath(str(container.login_dir))
        profile.setCachePath(str(container.login_dir / "cache"))
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        profile.clearAllVisitedLinks()
    profile.setHttpUserAgent(USER_AGENT)
    profile.setHttpAcceptLanguage("en-US,en;q=0.9")
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setSpellCheckEnabled(False)
    if hasattr(profile, "setPersistentPermissionsPolicy"):
        # PRISM decides every permission itself (Permission Control Center).
        profile.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
    sandbox = container.kind == "sandbox"
    container.interceptor = PrivacyInterceptor(engine, container.id, "sandbox" if sandbox else "normal")
    profile.setUrlRequestInterceptor(container.interceptor)

    # Third-party cookies are the backbone of cross-site tracking: refuse them.
    # (The filter runs on Chromium's IO thread: only hand data to a deque.)
    cid = container.id

    def cookie_filter(req, stats=engine.stats):
        if req.thirdParty or sandbox and req.firstPartyUrl.host() != req.origin.host():
            stats.cookies_refused += 1
            refused.append((cid, req.firstPartyUrl.host().lower(), req.origin.host().lower()))
            return False
        return True
    profile.cookieStore().setCookieFilter(cookie_filter)

    s = profile.settings()
    A = QWebEngineSettings.WebAttribute
    for attr, value in [
        (A.JavascriptCanOpenWindows, False),   # no scripted pop-ups / pop-unders
        (A.WebRTCPublicInterfacesOnly, True),  # don't leak LAN IPs over WebRTC
        (A.PluginsEnabled, False),
        # WebGL crashes Qt WebEngine 6.12 (e.g. GitHub's 3D globe takes the whole
        # app down) and is a major fingerprinting surface. Off.
        (A.WebGLEnabled, False),
        (A.DnsPrefetchEnabled, False),
        (A.HyperlinkAuditingEnabled, False),
        (A.LocalContentCanAccessRemoteUrls, False),
        # Off by default: with it on, any HTML file opened from disk could read
        # every other file the user can (SSH keys, the vault, ...). PRISM's own
        # pages get it back per page (see PrismWindow.apply_page_rules).
        (A.LocalContentCanAccessFileUrls, False),
        (A.FullScreenSupportEnabled, not sandbox),
        (A.PdfViewerEnabled, not sandbox),
        (A.ScrollAnimatorEnabled, True),
        (A.FocusOnNavigationEnabled, True),
        (A.JavascriptCanAccessClipboard, False),
        (A.LocalStorageEnabled, not sandbox),       # sandbox: no persistent site storage
        (A.JavascriptEnabled, not sandbox),         # sandbox: scripts off until you allow them
    ]:
        s.setAttribute(attr, value)
    return profile


class ContainersMixin:
    """Container management for PrismWindow."""

    containers: dict[str, Container]
    refused: deque

    def _clean_login_folders(self):
        """Delete saved-login folders no container uses any more (turned off,
        cleared, or locked by Windows when that happened last session)."""
        keep = set(self.settings["rememberLogins"].values())
        for folder in logins_dir().iterdir():
            if folder.is_dir() and folder.name not in keep:
                shutil.rmtree(folder, ignore_errors=True)

    def install_cosmetics(self):
        for c in self.containers.values():
            scripts = c.profile.scripts()
            for old in scripts.find("prism-cosmetic"):
                scripts.remove(old)
            scripts.insert(cosmetic_script(self.engine.site_allow))

    def container(self, cid: str) -> Container:
        c = self.containers.get(cid)
        if c is None:
            preset = next((p for p in CONTAINER_PRESETS if p[0] == cid), None)
            if preset is None:
                raise KeyError(cid)
            c = self._make_container(cid, preset[1], preset[2], "standard")
        return c

    def _make_container(self, cid, name, color, kind) -> Container:
        c = Container(cid, name, color, kind)
        folder = self.settings["rememberLogins"].get(cid) if kind == "standard" else None
        if folder:
            c.login_dir = logins_dir() / folder
        c.profile = build_content_profile(self.app, self.engine, c, self.refused)
        store = c.profile.cookieStore()
        store.cookieAdded.connect(lambda ck, c=c: self.on_cookie(c, ck, True))
        store.cookieRemoved.connect(lambda ck, c=c: self.on_cookie(c, ck, False))
        c.profile.downloadRequested.connect(lambda d, c=c: self.on_download(d, c))
        if hasattr(c.profile, "setNotificationPresenter"):
            c.profile.setNotificationPresenter(self.present_notification)
        scripts = c.profile.scripts()
        scripts.insert(cosmetic_script(self.engine.site_allow))
        if c.login_dir is not None:
            store.loadAllCookies()      # saved logins show up in the Containers panel
        self.containers[cid] = c
        return c

    def set_remember_logins(self, cid: str, on: bool):
        """Turn "Remember logins" on/off for a standard container."""
        if not any(p[0] == cid for p in CONTAINER_PRESETS):
            return
        rules = self.settings["rememberLogins"]
        if bool(rules.get(cid)) == on:
            return
        if on:
            rules[cid] = f"{cid}-{uuid4().hex[:8]}"
        else:
            rules.pop(cid, None)
        self.settings.save()
        self._rebuild_container(cid)

    def forget_logins(self, cid: str):
        """Erase a remembering container's saved logins by moving it to a fresh folder."""
        rules = self.settings["rememberLogins"]
        if not rules.get(cid):
            return
        rules[cid] = f"{cid}-{uuid4().hex[:8]}"
        self.settings.save()
        self._rebuild_container(cid)

    def _rebuild_container(self, cid: str):
        """Give a container a new profile (per current settings) and move its tabs over.

        A profile can't switch between memory and disk, so the old one is dropped.
        Every disk profile has its own folder, so old and new never share files;
        the old folder is deleted once the old profile is gone (and again at
        startup if Windows still had it locked).
        """
        old = self.containers.pop(cid, None)
        if old is None:
            return              # not started yet: its next tab picks up the setting
        new = self.container(cid)
        closed = list(self.closed)      # moved tabs aren't "closed": keep Ctrl+Shift+T clean
        for t in [t for t in self.tabs if t.container is old]:
            self.new_tab(t.url, activate=t is self.active, container=new)
            self.close_tab(t.id)
        self.closed = closed
        profile, folder = old.profile, old.login_dir
        old.profile = None
        QTimer.singleShot(1500, profile.deleteLater)
        if folder is not None:
            QTimer.singleShot(4000, lambda: shutil.rmtree(folder, ignore_errors=True))
        self.panel.push_section("containers")
        self.push_state()

    def new_temp_session(self, url: QUrl | None = None):
        self._temp_n += 1
        c = self._make_container(f"temp-{self._temp_n}", f"Temporary {self._temp_n}", TEMP_COLOR, "temp")
        self.new_tab(url or NEWTAB_URL, container=c, focus_address=url is None)
        self.bridge.toast.emit(f"Temporary session {self._temp_n}: everything in it is deleted when its last tab closes")

    def open_sandbox(self, url: QUrl | None = None):
        t = self.current()
        target = url if url is not None else (t.url if t and not is_newtab(t.url) else NEWTAB_URL)
        self._temp_n += 1
        c = self._make_container(f"sandbox-{self._temp_n}", "Sandbox", SANDBOX_COLOR, "sandbox")
        self.new_tab(target, container=c)
        self.bridge.toast.emit("Sandbox: scripts off, third-party requests blocked, nothing kept")

    def move_to_container(self, tab: "Tab", cid: str):
        url = tab.url
        self.new_tab(url, container=self.container(cid))
        self.close_tab(tab.id)

    def drop_container_if_empty(self, c: Container):
        if c.kind == "standard" or any(t.container is c for t in self.tabs):
            return
        self.containers.pop(c.id, None)
        profile = c.profile
        c.profile = None
        # Profiles must outlive their pages; the views were deleteLater()'d.
        QTimer.singleShot(1500, profile.deleteLater)

    def clear_container(self, c: Container):
        if c.login_dir is not None:
            self.forget_logins(c.id)    # also wipes site storage, which Qt can't clear in place
            return
        c.profile.cookieStore().deleteAllCookies()
        c.profile.clearHttpCache()
        c.profile.clearAllVisitedLinks()
        c.cookies.clear()

    # --- cookies
    def on_cookie(self, c: Container, ck, added: bool):
        key = (ck.domain(), ck.path(), bytes(ck.name()).decode("utf-8", "replace"))
        if not added:
            c.cookies.pop(key, None)
            return
        name = key[2]
        purpose, who = cookie_purpose(name)
        same = {0: "", 1: "None", 2: "Lax", 3: "Strict"}.get(int(ck.sameSitePolicy().value), "")
        c.cookies[key] = {
            "key": "\t".join(key), "name": name, "domain": ck.domain(), "path": ck.path(),
            "secure": ck.isSecure(), "httpOnly": ck.isHttpOnly(), "sameSite": same,
            "session": ck.isSessionCookie(),
            "expires": "" if ck.isSessionCookie() else ck.expirationDate().toString(Qt.DateFormat.ISODate),
            "size": len(bytes(ck.value())), "purpose": purpose, "who": who, "_cookie": ck,
        }

    def site_cookies(self, tab: "Tab") -> list[dict]:
        site = site_of(tab.url.host())
        if not site:
            return []
        return [{k: v for k, v in info.items() if k != "_cookie"}
                for info in tab.container.cookies.values()
                if site_of(info["domain"].lstrip(".")) == site]

    def delete_cookie(self, tab: "Tab", key: str):
        info = tab.container.cookies.get(tuple(key.split("\t")))
        if info:
            tab.container.profile.cookieStore().deleteCookie(info["_cookie"])
            tab.container.cookies.pop(tuple(key.split("\t")), None)

    def drain_refused(self):
        while self.refused:
            cid, first, origin = self.refused.popleft()
            site = site_of(first)
            for t in self.tabs:
                if t.container.id == cid and site_of(t.url.host()) == site:
                    t.log.cookies_refused.append({"origin": origin})
                    self.mark_dirty(t)
