"""PRISM site intelligence: per-tab request log, tracker map, cookie
purposes, response headers and the website trust score."""

from __future__ import annotations

import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from functools import lru_cache

from PyQt6.QtCore import QObject, pyqtSignal

from dohproxy import resolve, urllib_handlers
from stats import base_domain

MAX_LOG = 1500

RESOURCE_TYPES = {
    0: "document", 1: "subframe", 2: "stylesheet", 3: "script", 4: "image", 5: "font",
    6: "subresource", 7: "object", 8: "media", 9: "worker", 10: "sharedworker",
    11: "prefetch", 12: "favicon", 13: "xhr", 14: "ping", 15: "serviceworker",
    16: "cspreport", 17: "plugin", 18: "preload", 19: "navigationpreload",
    20: "csp-report", 21: "preflight", 22: "websocket", 255: "other",
}


@lru_cache(maxsize=8192)
def site_of(host: str) -> str:
    return base_domain(host.lower()) if host else ""


class TabLog:
    """Everything one tab's current page loaded (or tried to)."""

    def __init__(self) -> None:
        self.reset("")

    def reset(self, url: str) -> None:
        self.page_url = url
        self.started = time.time()
        self.entries: list[dict] = []
        self.cookies_refused: list[dict] = []
        self.mixed = 0
        self.dropped = 0

    def add(self, url: str, host: str, rtype: str, first_party: str, blocked: str = "") -> None:
        if len(self.entries) >= MAX_LOG:
            self.dropped += 1
            return
        third = bool(host) and site_of(host) != site_of(first_party)
        self.entries.append({"t": round((time.time() - self.started) * 1000), "url": url[:2000],
                             "host": host, "type": rtype, "third": third, "blocked": blocked})
        if url.startswith("http:") and self.page_url.startswith("https:"):
            self.mixed += 1

    # --- derived views
    def tracker_map(self, tracker_check) -> dict:
        groups: dict[str, dict] = {}
        for e in self.entries:
            if not e["third"] or not e["host"]:
                continue
            key = site_of(e["host"])
            g = groups.setdefault(key, {"site": key, "hosts": set(), "requests": 0, "blocked": 0,
                                        "types": defaultdict(int), "tracker": False})
            g["hosts"].add(e["host"])
            g["requests"] += 1
            g["types"][e["type"]] += 1
            if e["blocked"]:
                g["blocked"] += 1
            if e["blocked"] in ("tracker", "malware") or tracker_check(e["host"]):
                g["tracker"] = True
        out = []
        for g in groups.values():
            out.append({**g, "hosts": sorted(g["hosts"]), "types": dict(g["types"])})
        out.sort(key=lambda g: -g["requests"])
        return {"site": site_of(_host(self.page_url)), "nodes": out}

    def scripts(self) -> list[dict]:
        hosts: dict[str, dict] = {}
        for e in self.entries:
            if e["type"] != "script":
                continue
            h = hosts.setdefault(e["host"], {"host": e["host"], "third": e["third"], "count": 0,
                                             "blocked": "", "urls": []})
            h["count"] += 1
            if e["blocked"]:
                h["blocked"] = e["blocked"]
            if len(h["urls"]) < 8:
                h["urls"].append(e["url"])
        return sorted(hosts.values(), key=lambda h: (not h["third"], -h["count"]))


def _host(url: str) -> str:
    try:
        return url.split("://", 1)[1].split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    except IndexError:
        return ""


# --------------------------------------------------------------- cookies

COOKIE_PURPOSES = [
    # (prefix or exact name, purpose, who)
    ("_ga", "analytics", "Google Analytics"), ("_gid", "analytics", "Google Analytics"),
    ("_gat", "analytics", "Google Analytics"), ("_gcl_", "advertising", "Google Ads"),
    ("__utm", "analytics", "Google Analytics (legacy)"), ("_fbp", "advertising", "Meta Pixel"),
    ("_fbc", "advertising", "Meta Pixel"), ("fr", "advertising", "Meta"),
    ("_hj", "analytics", "Hotjar"), ("ajs_", "analytics", "Segment"),
    ("mp_", "analytics", "Mixpanel"), ("amplitude_", "analytics", "Amplitude"),
    ("_clck", "analytics", "Microsoft Clarity"), ("_clsk", "analytics", "Microsoft Clarity"),
    ("muid", "advertising", "Microsoft Ads"), ("_uet", "advertising", "Microsoft Ads"),
    ("ide", "advertising", "Google DoubleClick"), ("test_cookie", "advertising", "Google DoubleClick"),
    ("_pin_unauth", "advertising", "Pinterest"), ("_ttp", "advertising", "TikTok"),
    ("li_", "advertising", "LinkedIn"), ("bcookie", "advertising", "LinkedIn"),
    ("__cf_bm", "security", "Cloudflare bot management"), ("cf_clearance", "security", "Cloudflare"),
    ("__cfruid", "security", "Cloudflare"), ("_cfuvid", "security", "Cloudflare"),
    ("__stripe_", "security", "Stripe fraud prevention"),
    ("csrftoken", "security", "CSRF protection"), ("xsrf-token", "security", "CSRF protection"),
    ("_csrf", "security", "CSRF protection"), ("__host-", "security", "host-locked cookie"),
    ("phpsessid", "session", "PHP session"), ("jsessionid", "session", "Java session"),
    ("asp.net_sessionid", "session", "ASP.NET session"), ("connect.sid", "session", "Express session"),
    ("sessionid", "session", "login session"), ("session", "session", "session"),
    ("_session", "session", "session"), ("user_session", "session", "login session"),
    ("logged_in", "session", "login state"), ("_octo", "analytics", "GitHub"),
    ("optanonconsent", "consent", "OneTrust consent"), ("optanonalertboxclosed", "consent", "OneTrust consent"),
    ("cookieconsent", "consent", "cookie consent"), ("euconsent", "consent", "IAB consent string"),
    ("cookieyes", "consent", "CookieYes consent"), ("cmplz_", "consent", "Complianz consent"),
    ("intercom-", "support", "Intercom chat"), ("__hs", "analytics", "HubSpot"),
    ("hubspotutk", "analytics", "HubSpot"), ("_shopify", "session", "Shopify"),
    ("lang", "preference", "language"), ("locale", "preference", "language"),
    ("theme", "preference", "theme"), ("tz", "preference", "time zone"),
]


def cookie_purpose(name: str) -> tuple[str, str]:
    low = name.lower()
    for key, purpose, who in COOKIE_PURPOSES:
        if low == key or low.startswith(key):
            return purpose, who
    if "consent" in low:
        return "consent", "cookie consent"
    if "sess" in low or "auth" in low or "token" in low:
        return "session", "login / session"
    if "track" in low or "visitor" in low or "uid" in low:
        return "analytics", "visitor id"
    return "unknown", ""


# ------------------------------------------------------- headers + trust

SECURITY_HEADERS = {
    "strict-transport-security": "HSTS: forces HTTPS on future visits",
    "content-security-policy": "CSP: limits which scripts can run",
    "x-content-type-options": "Stops MIME-type sniffing",
    "referrer-policy": "Limits what URLs are leaked to other sites",
    "permissions-policy": "Restricts powerful browser features",
    "x-frame-options": "Prevents clickjacking via frames",
}


class HeaderFetcher(QObject):
    """Fetches a page's response headers out-of-band (no cookies sent)."""
    done = pyqtSignal(str, dict)

    def __init__(self, user_agent: str, parent=None) -> None:
        super().__init__(parent)
        self.ua = user_agent
        self.cache: dict[str, dict] = {}

    def fetch(self, url: str) -> None:
        if url in self.cache:
            self.done.emit(url, self.cache[url])
            return
        threading.Thread(target=self._run, args=(url,), daemon=True).start()

    def _run(self, url: str) -> None:
        result: dict = {"url": url, "fetched": int(time.time())}
        try:
            req = urllib.request.Request(url, method="GET", headers={
                "User-Agent": self.ua, "Accept": "text/html,*/*", "DNT": "1", "Sec-GPC": "1"})
            ctx = ssl.create_default_context()
            t0 = time.perf_counter()
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), *urllib_handlers())
            try:
                resp = opener.open(req, timeout=12)
            except urllib.error.HTTPError as err:
                resp = err
            result.update(ok=True, status=resp.status if hasattr(resp, "status") else resp.code,
                          headers=[[k, v] for k, v in resp.headers.items()],
                          finalUrl=resp.geturl(), timeMs=round((time.perf_counter() - t0) * 1000))
            resp.close()
            if url.startswith("https:"):
                result["tls"] = self._tls(url)
        except ssl.SSLCertVerificationError as exc:
            result.update(ok=False, certError=str(exc.verify_message or exc))
        except Exception as exc:  # noqa: BLE001
            result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        self.cache[url] = result
        self.done.emit(url, result)

    @staticmethod
    def _tls(url: str) -> dict:
        import socket
        host = _host(url)
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((resolve(host), 443), timeout=8) as sock, \
                    ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                issuer = dict(x[0] for x in cert.get("issuer", []))
                return {"version": tls.version(), "issuer": issuer.get("organizationName", ""),
                        "expires": cert.get("notAfter", ""), "cipher": (tls.cipher() or ("",))[0]}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}


def trust_score(*, url: str, log: TabLog, cookies: list[dict], headers: dict | None,
                malicious: bool, cert_error: str, tracker_check) -> dict:
    """Score 0-100 from observable signals. Each check reports its effect."""
    checks: list[dict] = []

    def check(label, state, delta, detail=""):
        checks.append({"label": label, "state": state, "delta": delta, "detail": detail})

    score = 100
    https = url.startswith("https:")
    if malicious:
        check("Known malicious domain", "fail", -100, "Listed in a malware or phishing feed")
    if cert_error:
        check("Certificate problem", "fail", -40, cert_error)
    if https:
        check("Encrypted connection (HTTPS)", "pass", 0)
    else:
        check("Not encrypted (HTTP)", "fail", -30, "Anything you send can be read in transit")
    if log.mixed:
        check("Mixed content", "warn", -10, f"{log.mixed} request(s) over plain HTTP")

    tmap = log.tracker_map(tracker_check)["nodes"]
    trackers = [n for n in tmap if n["tracker"]]
    third = len(tmap)
    if trackers:
        d = -min(30, 4 * len(trackers))
        check(f"{len(trackers)} tracking compan{'y' if len(trackers) == 1 else 'ies'} contacted", "warn", d,
              ", ".join(n["site"] for n in trackers[:6]))
    else:
        check("No known trackers", "pass", 0)
    if third > 12:
        check(f"{third} third-party domains", "warn", -min(10, third - 12), "Many outside services load on this page")
    elif third:
        check(f"{third} third-party domain{'s' if third != 1 else ''}", "info", 0)

    if log.cookies_refused:
        check(f"{len(log.cookies_refused)} third-party cookie(s) refused", "warn", -min(10, 2 * len(log.cookies_refused)),
              "Cross-site cookies were attempted and blocked")
    ad_cookies = [c for c in cookies if c["purpose"] in ("advertising", "analytics")]
    if ad_cookies:
        check(f"{len(ad_cookies)} analytics / advertising cookie(s)", "warn", -min(10, 2 * len(ad_cookies)),
              ", ".join(sorted({c['who'] or c['name'] for c in ad_cookies})[:5]))

    if headers and headers.get("ok"):
        present = {k.lower() for k, _ in headers.get("headers", [])}
        missing = [h for h in SECURITY_HEADERS if h not in present]
        have = [h for h in SECURITY_HEADERS if h in present]
        if have:
            check(f"{len(have)} of {len(SECURITY_HEADERS)} security headers", "pass" if len(missing) <= 2 else "info", 0,
                  ", ".join(have))
        if missing and https:
            d = -min(12, 2 * len(missing))
            check(f"Missing: {', '.join(missing[:3])}{'…' if len(missing) > 3 else ''}", "warn", d,
                  "; ".join(SECURITY_HEADERS[m] for m in missing))
    elif headers is None and https:
        check("Security headers", "info", 0, "Checking…")

    score += sum(c["delta"] for c in checks)
    score = max(0, min(100, score))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"
    return {"score": score, "grade": grade, "checks": checks}
