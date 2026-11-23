"""PRISM ad / tracker blocking, network protection and request hardening.

Network-level blocking: every request made by any tab passes through a
`PrivacyInterceptor` (one per container profile), which asks the shared
`PrivacyEngine` what to do. Requests are cancelled before they leave the
machine when their host (or any parent domain) is:
  * an ad / tracker domain           blocklists/*.txt, blocklists/downloaded/*.txt
  * a malware / phishing domain      blocklists/security/*.txt (+ downloaded/security)
  * on the user's own block list     (Network panel)
  * a script the site's script rules block (Site panel)
Supported list formats:
    0.0.0.0 ads.example.com      (hosts file)
    ||ads.example.com^           (Adblock / AdGuard DNS style)
    ads.example.com              (plain domain)
    @@||cdn.example.com^         (allow rule, overrides blocks)
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import (
    QWebEngineScript,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

from siteintel import RESOURCE_TYPES, site_of
from stats import SessionStats

from paths import RESOURCES as ROOT, user_blocklists_dir

LIST_DIRS = [ROOT / "blocklists", ROOT / "blocklists" / "downloaded"]
SECURITY_DIRS = [ROOT / "blocklists" / "security", ROOT / "blocklists" / "downloaded" / "security"]
_USER_LISTS = user_blocklists_dir()          # built app: lists from `PRISM --update-blocklists`
if _USER_LISTS is not None:
    LIST_DIRS.append(_USER_LISTS)
    SECURITY_DIRS.append(_USER_LISTS / "security")
COSMETIC_CSS = ROOT / "blocklists" / "cosmetic.css"

_SKIP = {"localhost", "localhost.localdomain", "local", "broadcasthost",
         "0.0.0.0", "127.0.0.1", "::1", "ip6-localhost", "ip6-loopback"}

# Query parameters that exist only to track you across sites.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid",
    "mc_cid", "mc_eid", "igshid", "_hsenc", "_hsmi", "mkt_tok", "ref_src",
    "oly_anon_id", "oly_enc_id", "vero_id", "__s", "s_cid", "twclid",
}

RT = QWebEngineUrlRequestInfo.ResourceType
MAIN_FRAME = RT.ResourceTypeMainFrame
SCRIPT = RT.ResourceTypeScript

# Local files. A page opened from disk gets file access back (see
# PrismWindow.apply_page_rules), or a saved page would show without its
# images and styles. But Qt's file access is all or nothing: on its own it
# would let any HTML file read every other file you have. So here a local page
# may only load what a page is made of (styles, scripts, images, fonts, media,
# frames of other pages), only from its own folder or below, and never read a
# file from script (fetch / XHR), which is how a page would steal one.
# It can't send anything anywhere either: LocalContentCanAccessRemoteUrls is off.
UI_DIR = (ROOT / "ui").resolve()
LOCAL_PARTS = {RT.ResourceTypeStylesheet, SCRIPT, RT.ResourceTypeImage, RT.ResourceTypeFontResource,
               RT.ResourceTypeMedia, RT.ResourceTypeFavicon, RT.ResourceTypeSubFrame}
FRAME_FILES = {".html", ".htm", ".xhtml", ".shtml", ".svg", ".mhtml", ".mht"}


def local_file_allowed(url: QUrl, first_party: QUrl, rtype) -> bool:
    """May the page at `first_party` load the local file `url` (not as the main frame)?"""
    if not first_party.isLocalFile():
        return False                                 # websites never read your files
    try:
        page = Path(first_party.toLocalFile()).resolve()
        target = Path(url.toLocalFile()).resolve()
    except (OSError, ValueError):
        return False
    if page.parent == UI_DIR or target == page:      # PRISM's own pages; a file reading itself (PDF viewer)
        return True
    if rtype not in LOCAL_PARTS or not target.is_relative_to(page.parent):
        return False
    return rtype != RT.ResourceTypeSubFrame or target.suffix.lower() in FRAME_FILES


def _parse_line(line: str) -> tuple[str | None, bool]:
    """Return (domain, is_allow_rule) for one blocklist line."""
    line = line.strip()
    if not line or line[0] in "#!" or line.startswith("["):
        return None, False
    allow = line.startswith("@@")
    if allow:
        line = line[2:]
    if line.startswith("||"):
        if "$" in line or "/" in line or "*" in line:
            return None, False  # path / option rules are out of scope
        domain = line[2:].rstrip("^|")
    else:
        parts = line.split("#", 1)[0].split()
        if not parts:
            return None, False
        domain = parts[1] if len(parts) > 1 and parts[0] in ("0.0.0.0", "127.0.0.1", "::") else parts[0]
    domain = domain.strip().strip(".").lower()
    if not domain or domain in _SKIP or "." not in domain or "/" in domain:
        return None, False
    return domain, allow


def _load(folders: list[Path]) -> tuple[set[str], set[str], list[str]]:
    block, allow, sources = set(), set(), []
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.txt")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            sources.append(path.name)
            for line in text.splitlines():
                domain, is_allow = _parse_line(line)
                if domain:
                    (allow if is_allow else block).add(domain)
    return block, allow, sources


def _match(host: str, block: set[str], allow: set[str] = frozenset()) -> bool:
    labels = host.lower().rstrip(".").split(".")
    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        if candidate in allow:
            return False
        if candidate in block:
            return True
    return False


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


class Blocklist:
    def __init__(self) -> None:
        self.block: set[str] = set()
        self.allow: set[str] = set()
        self.malware: set[str] = set()
        self.sources: list[str] = []
        self.security_sources: list[str] = []
        self.reload()

    def reload(self) -> None:
        self.block, self.allow, self.sources = _load(LIST_DIRS)
        self.malware, _, self.security_sources = _load(SECURITY_DIRS)

    def is_blocked(self, host: str) -> bool:
        return _match(host, self.block, self.allow)

    def is_malicious(self, host: str) -> bool:
        return bool(self.malware) and _match(host, self.malware)

    def __len__(self) -> int:
        return len(self.block)


def strip_tracking(url: QUrl) -> QUrl | None:
    """Return a copy of `url` without tracking parameters, or None if clean."""
    if not url.hasQuery():
        return None
    raw = bytes(url.toEncoded()).decode("ascii", errors="ignore")
    base, frag = raw.split("#", 1) if "#" in raw else (raw, None)
    if "?" not in base:
        return None
    path, query = base.split("?", 1)
    parts = [p for p in query.split("&") if p]
    kept = []
    for p in parts:
        key = p.split("=", 1)[0].lower()
        if key in TRACKING_PARAMS or key.startswith("utm_"):
            continue
        kept.append(p)
    if len(kept) == len(parts):
        return None
    new = path + ("?" + "&".join(kept) if kept else "") + ("#" + frag if frag is not None else "")
    return QUrl.fromEncoded(new.encode("ascii"))


class PrivacyEngine:
    """State shared by every container: lists, rules, counters."""

    def __init__(self, blocklist: Blocklist, settings, on_block=None, stats_path: Path | None = None) -> None:
        self.blocklist = blocklist
        self.settings = settings
        self.on_block = on_block          # callback(container, first_party, host, url, rtype, reason)
        self.site_allow: set[str] = set() # hosts where the shield is off
        self.malware_allow: set[str] = set()   # "continue anyway" on a warning page
        self.counts: dict[str, int] = {}  # first-party host -> blocked this page
        self.malicious_hits: dict[str, str] = {}   # blocked main-frame URL -> host
        self.stats = SessionStats(stats_path)
        self.custom: set[str] = set()
        self.reload_custom()

    def reload_custom(self) -> None:
        self.custom = {h.strip().lower().strip(".") for h in self.settings["customBlocks"] if h.strip()}

    @property
    def total(self) -> int:
        return self.stats.blocked

    def shield_off_for(self, host: str) -> bool:
        return bool(host) and host.lower() in self.site_allow

    def is_tracker(self, host: str) -> bool:
        return self.blocklist.is_blocked(host)

    def decide(self, info: QWebEngineUrlRequestInfo, mode: str, container: str) -> None:
        url = info.requestUrl()
        host = url.host().lower()
        first_party = info.firstPartyUrl().host().lower()
        rtype = info.resourceType()
        is_main = rtype == MAIN_FRAME

        web = url.scheme() in ("http", "https", "ws", "wss")
        if web:
            self.stats.request()

        if is_main:
            self.counts[host] = 0
            cleaned = strip_tracking(url)
            if cleaned is not None:
                self.stats.stripped += 1
                info.redirect(cleaned)
                return
            if web:
                is_search = ((host.endswith("libresearch.ca") and url.path().startswith("/search"))
                             or (host == "duckduckgo.com" and "q=" in url.query()))
                self.stats.page(host, url.scheme() == "https", is_search)

        if url.scheme() == "file":
            if not is_main and not local_file_allowed(url, info.firstPartyUrl(), rtype):
                info.block(True)
            return

        info.setHttpHeader(b"DNT", b"1")
        info.setHttpHeader(b"Sec-GPC", b"1")

        if not host or not web:
            return

        prot = self.settings["protection"]
        reason = ""
        # 1. malware / phishing: always first, even with the shield off
        if prot.get("malware", True) and self.blocklist.is_malicious(host) and host not in self.malware_allow \
                and site_of(host) not in self.malware_allow:
            reason = "malware"
            if is_main:
                self.malicious_hits[url.toString()] = host
        # 2. the user's own block list
        elif self.custom and _match(host, self.custom):
            reason = "custom"
        elif not (self.shield_off_for(first_party) or (is_main and self.shield_off_for(host))):
            third = site_of(host) != site_of(first_party)
            # 3. sandbox: nothing third-party at all
            if mode == "sandbox" and third and not is_main:
                reason = "sandbox"
            # 4. ads / trackers
            elif self.blocklist.is_blocked(host):
                reason = "tracker"
            elif rtype == SCRIPT and first_party:
                rule = self.settings.scripts_for(site_of(first_party))
                if host in rule["blockedHosts"] or site_of(host) in rule["blockedHosts"]:
                    reason = "script-rule"
                elif third and rule["thirdParty"] == "block":
                    reason = "third-party-script"
                # 5. suspicious scripts: third-party code served from a bare IP
                elif third and prot.get("suspiciousScripts", True) and _is_ip(host):
                    reason = "suspicious"

        if reason:
            info.block(True)
            self.stats.block(host, first_party)
            self.counts[first_party] = self.counts.get(first_party, 0) + 1
            if self.on_block:
                self.on_block(container, first_party, host, url.toString(),
                              RESOURCE_TYPES.get(int(rtype.value), "other"), reason)


class PrivacyInterceptor(QWebEngineUrlRequestInterceptor):
    """One per container profile; `mode` is "normal" or "sandbox"."""

    def __init__(self, engine: PrivacyEngine, container: str, mode: str = "normal", parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.container = container
        self.mode = mode

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
        self.engine.decide(info, self.mode, self.container)


class RequestLogger(QWebEngineUrlRequestInterceptor):
    """Per-page: records every request that got past the blocker."""

    def __init__(self, callback, parent=None) -> None:
        super().__init__(parent)
        self.callback = callback

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
        url = info.requestUrl()
        if url.scheme() not in ("http", "https", "ws", "wss"):
            return
        self.callback(url.toString(), url.host().lower(),
                      RESOURCE_TYPES.get(int(info.resourceType().value), "other"),
                      info.firstPartyUrl().host().lower(), info.resourceType() == MAIN_FRAME)


def cosmetic_script(site_allow: set[str]) -> QWebEngineScript:
    """Script that hides leftover ad slots (runs in an isolated JS world)."""
    try:
        css = COSMETIC_CSS.read_text(encoding="utf-8")
    except OSError:
        css = ""
    src = """
(function () {
  var allow = %s;
  var h = location.hostname.toLowerCase();
  if (allow.indexOf(h) !== -1) return;
  var css = %s;
  function add() {
    var root = document.head || document.documentElement;
    if (!root) { return setTimeout(add, 0); }
    var s = document.createElement('style');
    s.setAttribute('data-prism', 'cosmetic');
    s.textContent = css;
    root.appendChild(s);
  }
  add();
})();
""" % (json.dumps(sorted(site_allow)), json.dumps(css))
    script = QWebEngineScript()
    script.setName("prism-cosmetic")
    script.setSourceCode(src)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
    script.setRunsOnSubFrames(True)
    return script
