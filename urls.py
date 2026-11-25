"""PRISM addresses: the local UI pages, the search engine (SearXNG) and how
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
TIMEMACHINE_URL = QUrl.fromLocalFile(str(UI / "timemachine.html"))
ICON = ROOT / "assets" / "icon.png"

SEARCH_NAME = "SearXNG"
# Public SearXNG instances, tried in this order. SearXNG is open-source
# metasearch: it asks several engines for you and returns the results
# without ads, tracking or a profile. Instances come and go and rate-limit
# busy IPs, so PRISM moves on to the next one when an instance refuses
# (see PrismWindow.search_for); your own instance (Panel → Network) goes first.
SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://search.inetol.net",
    "https://priv.au",
    "https://paulgo.io",
    "https://baresearch.org",
    "https://searx.tiekoetter.com",
    "https://opnxng.com",
    "https://search.sapti.me",
]
SEARCH_FLAGS = [("categories", "general"), ("language", "auto"), ("safesearch", "0")]
INSTANCE_RETRY_SECONDS = 600                    # skip a refusing instance for 10 min

# What a SearXNG instance shows when it refuses a search: its rate limiter,
# a proxy error, or a bot check that gave up on PRISM. A browser check
# ("Checking your browser") usually passes by itself, so it only counts once
# it has failed (go-away's "Automated verification failed", Anubis's "Oh
# noes!", Cloudflare's "you have been blocked"), or with `stuck` (polled
# again after SEARCH_STUCK_MS) if it is still spinning. Checked in an
# isolated JS world so the page can't tamper with the check.
_SEARCH_CHECK_JS = r"""(function (stuck) {
  if (document.querySelector('article.result')) return false;
  var t = document.body ? document.body.innerText.slice(0, 2000) : "";
  if (/^\s*too many requests|rate limit(ed)? exceeded|^\s*(403 )?forbidden|access denied|^\s*(502 )?bad gateway|^\s*(503 )?service (temporarily )?unavailable/im.test(t)) return true;
  if (/automated verification failed|verification failed|try the automated checks a second time|^\s*oh noes!|you have been blocked|challenge failed/im.test(t)) return true;
  return stuck && /checking your browser|verifying (that )?you are (a )?human|making sure you('|’)?re not a bot|just a moment\.\.\./im.test(t);
})(STUCK)"""
SEARCH_ERROR_JS = _SEARCH_CHECK_JS.replace("STUCK", "false")
SEARCH_STUCK_JS = _SEARCH_CHECK_JS.replace("STUCK", "true")
SEARCH_STUCK_MS = 20_000

# TLDs we treat as "this is a web address" when no scheme is typed. Kept
# programmer-safe: "os.path.join" or "main.py" should be searched, not visited.
TLDS = set("""com org net io dev app ai co gov edu mil int info biz me tv
xyz tech cloud sh so gg to fm ly is it de fr uk ca au nz jp cn kr in br es nl
se no fi dk pl ch at be cz ru ua eu us site online page wiki blog news""".split())


def clean_instance(text: str) -> str:
    """"searx.example.org/" -> "https://searx.example.org" ("" if it isn't an address)."""
    t = text.strip().rstrip("/")
    if not t:
        return ""
    url = QUrl(t if "://" in t else "https://" + t)
    if url.scheme() not in ("http", "https") or not url.host() or "." not in url.host() and url.host() != "localhost":
        return ""
    port = f":{url.port()}" if url.port() != -1 else ""
    path = url.path().rstrip("/")
    return f"{url.scheme()}://{url.host().lower()}{port}{path}"


def search_url(query: str, instance: str = SEARXNG_INSTANCES[0]) -> QUrl:
    # urlencode escapes + & # % correctly, so "c++" or "a&b" survive intact.
    return QUrl.fromEncoded((instance.rstrip("/") + "/search?" + urlencode([("q", query), *SEARCH_FLAGS])).encode("ascii"))


def instance_of(url: QUrl) -> str:
    """The SearXNG instance a search URL belongs to ("" when it is not a search)."""
    path = url.path()
    if not path.endswith("/search"):
        return ""
    port = f":{url.port()}" if url.port() != -1 else ""
    return f"{url.scheme()}://{url.host().lower()}{port}{path[:-len('/search')]}"


def is_search(url: QUrl, custom: str = "") -> bool:
    inst = instance_of(url)
    return bool(inst) and (inst in SEARXNG_INSTANCES or (bool(custom) and inst == custom.rstrip("/")))


def query_of(url: QUrl) -> str:
    raw = bytes(url.toEncoded()).decode("ascii", "ignore")
    query = raw.split("#", 1)[0].split("?", 1)[1] if "?" in raw else ""
    return (parse_qs(query).get("q") or [""])[0].strip()


def resolve_input(text: str, search=None) -> QUrl:
    """Turn address-bar input into a URL or a SearXNG query."""
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
