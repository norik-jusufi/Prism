"""PRISM addresses: the local UI pages, the search engines and how
address-bar input turns into a URL."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from PyQt6.QtCore import QUrl

from paths import RESOURCES as ROOT
UI = ROOT / "ui"
NEWTAB_URL = QUrl.fromLocalFile(str(UI / "newtab.html"))
CHROME_URL = QUrl.fromLocalFile(str(UI / "chrome.html"))
PANEL_URL = QUrl.fromLocalFile(str(UI / "panel.html"))
WARNING_URL = QUrl.fromLocalFile(str(UI / "warning.html"))
ICON = ROOT / "assets" / "icon.png"

SEARCH_NAME = "LibreSearch"
SEARCH_ENDPOINT = "https://www.libresearch.ca/search"
SEARCH_FLAGS = [("filterads", "1"), ("blockads", "1"), ("blocktrackers", "1")]

# Backup engine, used automatically while LibreSearch is failing.
FALLBACK_NAME = "DuckDuckGo"
FALLBACK_ENDPOINT = "https://duckduckgo.com/"
# dark theme, ads off, no install / newsletter / upgrade promos
FALLBACK_FLAGS = [("kae", "d"), ("k1", "-1"), ("kak", "-1"), ("kax", "-1"),
                  ("kaq", "-1"), ("kap", "-1"), ("kao", "-1"), ("kau", "-1")]
LIBRE_RETRY_SECONDS = 300                       # retry LibreSearch after 5 min

# Text LibreSearch shows when its backend fails. Checked in an isolated JS
# world so the page can't tamper with the check.
LIBRE_ERROR_JS = r"""(function () {
  var t = document.body ? document.body.innerText : "";
  return /backend rejected the request|search (backend|service) (is )?unavailable|temporarily unavailable|too many requests/i.test(t);
})()"""

# TLDs we treat as "this is a web address" when no scheme is typed. Kept
# programmer-safe: "os.path.join" or "main.py" should be searched, not visited.
TLDS = set("""com org net io dev app ai co gov edu mil int info biz me tv
xyz tech cloud sh so gg to fm ly is it de fr uk ca au nz jp cn kr in br es nl
se no fi dk pl ch at be cz ru ua eu us site online page wiki blog news""".split())


def _engine_url(endpoint: str, flags, query: str) -> QUrl:
    # urlencode escapes + & # % correctly, so "c++" or "a&b" survive intact.
    return QUrl.fromEncoded((endpoint + "?" + urlencode([("q", query), *flags])).encode("ascii"))


def search_url(query: str) -> QUrl:
    return _engine_url(SEARCH_ENDPOINT, SEARCH_FLAGS, query)


def fallback_url(query: str) -> QUrl:
    return _engine_url(FALLBACK_ENDPOINT, FALLBACK_FLAGS, query)


def is_libre_search(url: QUrl) -> bool:
    return url.host().lower().endswith("libresearch.ca") and url.path().startswith("/search")


def query_of(url: QUrl) -> str:
    raw = bytes(url.toEncoded()).decode("ascii", "ignore")
    query = raw.split("#", 1)[0].split("?", 1)[1] if "?" in raw else ""
    return (parse_qs(query).get("q") or [""])[0].strip()


def resolve_input(text: str, search=None) -> QUrl:
    """Turn address-bar input into a URL or a LibreSearch query."""
    t = text.strip()
    if not t:
        return NEWTAB_URL
    if re.match(r"^[a-zA-Z][\w+.-]*://", t) or t.startswith(("about:", "view-source:", "data:")):
        return QUrl(t)
    if " " not in t:
        if re.match(r"^(localhost|\d{1,3}(\.\d{1,3}){3}|\[[0-9a-fA-F:]+\])(:\d+)?([/?#].*)?$", t):
            return QUrl("http://" + t)
        m = re.match(r"^([\w-]+(\.[\w-]+)+)(:\d+)?([/?#].*)?$", t)
        if m and m.group(1).rsplit(".", 1)[-1].lower() in TLDS:
            return QUrl("https://" + t)
    return (search or search_url)(t)


def is_newtab(url: QUrl) -> bool:
    return url.matches(NEWTAB_URL, QUrl.UrlFormattingOption.StripTrailingSlash) or url.isEmpty()


def is_local_ui(url: QUrl) -> bool:
    """One of PRISM's own pages in ./ui (new tab, warning page)."""
    return url.isLocalFile() and Path(url.toLocalFile()).resolve().parent == UI.resolve()


def is_warning(url: QUrl) -> bool:
    return is_local_ui(url) and url.toLocalFile().endswith("warning.html")
