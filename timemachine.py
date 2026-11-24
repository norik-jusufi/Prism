"""PRISM Privacy Time Machine: a flight recorder for what a website does to you.

Every tab records what its page did while it loaded and ran: which servers it
contacted, which scripts ran (and which PRISM stopped), what data it tried to
collect (cookies, fingerprinting probes, storage, beacons, permissions) and
which protection stopped what. The Time Machine view (ui/timemachine.*) lets
you rewind and replay that recording on a timeline.

Privacy of the recording itself:
  * metadata only: hosts, resource types, timings, block reasons, cookie and
    storage *names* (never values), API names. No page content, no form input,
    no request bodies, no query strings.
  * page addresses are kept as origin only (https://example.com), script
    addresses as host + file name. "Record full URLs" (off by default) keeps
    the whole address, minus the #fragment.
  * memory only: never written to disk unless you press Export. Closing the tab
    drops its recordings; Purge wipes them all.

Fingerprinting probes are seen by a small watcher injected into each page's
main world (it has to be: that is where the page's own scripts call the APIs).
It only reports *that* an API was used, by which script host, through console
messages carrying a per-session random token, so a page can't fake entries
without knowing it. It can be switched off in the Time Machine.
"""

from __future__ import annotations

import json
import secrets
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWebEngineCore import QWebEngineScript
from PyQt6.QtWidgets import QFileDialog

from siteintel import site_of

if TYPE_CHECKING:
    from tabs import Tab
    from window import PrismWindow

MAX_EVENTS = 6000          # per recording; later events only count as "dropped"
MAX_ARCHIVE = 8            # recordings kept per tab (this page + earlier ones)
PUSH_MS = 400              # live refresh of the open Time Machine

# Why a request was stopped -> the protection that did it.
PROTECTIONS = {
    "tracker":            ("Tracker blocklist", "Ad and tracking domains from the loaded blocklists"),
    "malware":            ("Malware & phishing shield", "Known malicious domains"),
    "custom":             ("Your block list", "Hosts you blocked yourself (Network panel)"),
    "sandbox":            ("Sandbox isolation", "Sandbox tabs load nothing from other sites"),
    "script-rule":        ("Site script rules", "Script hosts you blocked for this site"),
    "third-party-script": ("Third-party script block", "This site may only run its own scripts"),
    "suspicious":         ("Suspicious-script guard", "Third-party code served from a bare IP address"),
    "cookie-wall":        ("Third-party cookie wall", "Cross-site cookies are refused"),
    "strip":              ("Link cleaner", "Tracking parameters removed from the address"),
    "permission":         ("Permission guard", "Device and data permissions denied or blocked"),
}

PROBE_JS = r"""(function () {
  'use strict';
  var TOKEN = '%TOKEN%';
  var log = console.debug.bind(console);
  var JSONs = JSON.stringify;
  var seen = Object.create(null);
  var budget = 600;
  var re = /(https?:\/\/[^\s()'"]+?):\d+:\d+/;
  // Wrapped functions must stringify exactly like the originals, or the
  // watcher itself would make PRISM users stand out to fingerprinters.
  var real = new WeakMap();
  var ts = Function.prototype.toString;
  var tsp = new Proxy(ts, { apply: function (t, self, args) { return Reflect.apply(t, real.get(self) || self, args); } });
  real.set(tsp, ts);
  try { Object.defineProperty(Function.prototype, 'toString', { value: tsp, writable: true, enumerable: false, configurable: true }); } catch (e) {}
  function scriptHost() {
    var st = '';
    try { st = new Error().stack || ''; } catch (e) {}
    var lines = st.split('\n');
    for (var i = 1; i < lines.length; i++) {
      var m = re.exec(lines[i]);
      if (m) { try { return new URL(m[1]).host; } catch (e) { return ''; } }
    }
    return '';
  }
  function report(api, detail) {
    if (budget <= 0) return;
    var s = scriptHost();
    var key = api + '|' + s + '|' + (detail || '');
    if (seen[key]) return;
    seen[key] = 1;
    budget--;
    try { log(TOKEN + JSONs({ a: api, s: s, d: String(detail || '').slice(0, 80) })); } catch (e) {}
  }
  function hook(obj, name, api, detail) {
    try {
      var d = Object.getOwnPropertyDescriptor(obj, name);
      if (!d || typeof d.value !== 'function') return;
      var p = new Proxy(d.value, { apply: function (t, self, args) {
        try { var r = detail ? detail(self, args) : ''; if (r !== null) report(api, r); } catch (e) {}
        return Reflect.apply(t, self, args);
      } });
      real.set(p, d.value);
      Object.defineProperty(obj, name, { value: p, writable: d.writable, enumerable: d.enumerable, configurable: d.configurable });
    } catch (e) {}
  }
  function hookCtor(name, api) {
    try {
      var C = window[name];
      if (typeof C !== 'function') return;
      var p = new Proxy(C, { construct: function (t, args, nt) { report(api, name); return Reflect.construct(t, args, nt); } });
      real.set(p, C);
      Object.defineProperty(window, name, { value: p, writable: true, enumerable: false, configurable: true });
    } catch (e) {}
  }
  function hostOf(u) { try { return new URL(String(u), location.href).host; } catch (e) { return ''; } }
  var P = window;
  if (P.HTMLCanvasElement) {
    hook(HTMLCanvasElement.prototype, 'toDataURL', 'canvas-read');
    hook(HTMLCanvasElement.prototype, 'toBlob', 'canvas-read');
  }
  if (P.CanvasRenderingContext2D) {
    hook(CanvasRenderingContext2D.prototype, 'getImageData', 'canvas-read');
    var measured = 0;
    hook(CanvasRenderingContext2D.prototype, 'measureText', 'font-probe', function () {
      measured++; return measured === 60 ? '60+ text measurements' : null;
    });
  }
  [P.WebGLRenderingContext, P.WebGL2RenderingContext].forEach(function (G) {
    if (!G) return;
    hook(G.prototype, 'getParameter', 'webgl-id', function (self, a) {
      return (a[0] === 37445 || a[0] === 37446) ? 'unmasked GPU vendor / renderer' : null;
    });
  });
  hookCtor('OfflineAudioContext', 'audio-fp');
  hookCtor('RTCPeerConnection', 'webrtc');
  if (P.Navigator) {
    hook(Navigator.prototype, 'getBattery', 'battery');
    hook(Navigator.prototype, 'sendBeacon', 'beacon', function (s, a) { return hostOf(a[0]); });
  }
  if (P.MediaDevices) hook(MediaDevices.prototype, 'enumerateDevices', 'devices');
  if (P.Clipboard) { hook(Clipboard.prototype, 'readText', 'clipboard'); hook(Clipboard.prototype, 'read', 'clipboard'); }
  if (P.NavigatorUAData) hook(NavigatorUAData.prototype, 'getHighEntropyValues', 'ua-hints', function (s, a) {
    try { return (a[0] || []).slice(0, 6).join(', '); } catch (e) { return ''; }
  });
  if (P.Storage) hook(Storage.prototype, 'setItem', 'storage', function (self, a) {
    var kind = '';
    try { kind = self === P.sessionStorage ? 'session' : 'local'; } catch (e) {}
    return kind + ': ' + String(a[0]).slice(0, 48);
  });
  if (P.IDBFactory) hook(IDBFactory.prototype, 'open', 'idb', function (s, a) { return String(a[0]).slice(0, 48); });
  try {
    var cd = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
    if (cd && cd.set) {
      var setp = new Proxy(cd.set, { apply: function (t, self, args) {
        try { report('doc-cookie', String(args[0]).split('=')[0].trim().slice(0, 48)); } catch (e) {}
        return Reflect.apply(t, self, args);
      } });
      real.set(setp, cd.set);
      Object.defineProperty(Document.prototype, 'cookie', { get: cd.get, set: setp, enumerable: cd.enumerable, configurable: true });
    }
  } catch (e) {}
  var WATCH = { mousemove: 1, keydown: 1, keyup: 1, keypress: 1, input: 1, pointermove: 1, touchmove: 1,
                copy: 1, paste: 1, scroll: 1, visibilitychange: 1 };
  if (P.EventTarget) hook(EventTarget.prototype, 'addEventListener', 'listener', function (self, a) {
    var t = a[0];
    return (typeof t === 'string' && WATCH[t] === 1) ? t : null;
  });
})();"""


def probe_script(token: str) -> QWebEngineScript:
    s = QWebEngineScript()
    s.setName("prism-timemachine")
    s.setSourceCode(PROBE_JS.replace("%TOKEN%", token))
    s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    s.setRunsOnSubFrames(True)
    return s


def _short_script(url: str) -> str:
    """Host + file name of a script URL: enough to tell gtm.js from app.js."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    name = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return name[:60]


class Recording:
    _next = 1

    def __init__(self, url: str, full: bool, container: str):
        self.id = Recording._next
        Recording._next += 1
        parts = urlsplit(url)
        self.origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme else url
        self.url = url.split("#", 1)[0][:2000] if full else self.origin
        self.host = (parts.hostname or "").lower()
        self.site = site_of(self.host)
        self.container = container
        self.title = ""
        self.started = time.time()
        self.events: list[dict] = []
        self.hosts: dict[str, dict] = {}
        self.dropped = 0
        self.loaded_ms: int | None = None
        self._cookies: set[str] = set()

    def ms(self) -> int:
        return round((time.time() - self.started) * 1000)

    def add(self, ev: dict) -> None:
        if len(self.events) >= MAX_EVENTS:
            self.dropped += 1
            return
        ev["t"] = self.ms()
        self.events.append(ev)

    def meta(self, live: bool) -> dict:
        return {"id": self.id, "origin": self.origin, "url": self.url, "host": self.host, "site": self.site,
                "title": self.title, "container": self.container, "started": round(self.started * 1000),
                "elapsed": self.ms(), "live": live, "dropped": self.dropped, "loaded": self.loaded_ms,
                "count": len(self.events)}


class TimeMachine(QObject):
    """Keeps every tab's recordings and feeds the Time Machine view."""

    def __init__(self, window: "PrismWindow"):
        super().__init__(window)
        self.w = window
        self.token = "prism-tm-" + secrets.token_hex(16) + ":"
        conf = window.settings.data.setdefault("timeMachine", {})
        conf.setdefault("probes", True)
        conf.setdefault("fullUrls", False)
        self.recs: dict[int, deque[Recording]] = {}

    @property
    def conf(self) -> dict:
        return self.w.settings["timeMachine"]

    # --------------------------------------------------------- recording
    def recordings(self, tab: "Tab") -> deque[Recording]:
        return self.recs.setdefault(tab.id, deque(maxlen=MAX_ARCHIVE))

    def current(self, tab: "Tab") -> Recording | None:
        r = self.recs.get(tab.id)
        return r[-1] if r else None

    def begin(self, tab: "Tab", url: str) -> None:
        recs = self.recordings(tab)
        carried: list[dict] = []
        prev = recs[-1] if recs else None
        # The link cleaner turns one navigation into two main-frame requests
        # (tracking URL, then the clean one): keep that as one recording.
        if prev and prev.ms() < 2000 and len(prev.events) <= 4 \
                and all(e["k"] in ("nav", "strip", "req") for e in prev.events):
            recs.pop()
            carried = [e for e in prev.events if e["k"] == "strip"]
        rec = Recording(url, self.conf.get("fullUrls", False), tab.container.name)
        recs.append(rec)
        self._host(rec, rec.host)
        rec.add({"k": "nav", "h": rec.host})
        for ev in carried + tab.tm_pending:
            rec.add(ev)
        tab.tm_pending = []

    def _host(self, rec: Recording, host: str) -> None:
        if host and host not in rec.hosts:
            site = site_of(host)
            rec.hosts[host] = {"site": site, "third": site != rec.site,
                               "tracker": self.w.engine.is_tracker(host)}

    def add(self, tab: "Tab", ev: dict) -> None:
        rec = self.current(tab)
        if rec is None:
            return
        host = ev.get("h", "")
        if host:
            self._host(rec, host)
        if ev.get("s"):
            self._host(rec, ev["s"])
        rec.add(ev)

    def request(self, tab: "Tab", url: str, host: str, rtype: str, blocked: str = "") -> None:
        ev = {"k": "blk" if blocked else "req", "h": host, "ty": rtype}
        if blocked:
            ev["r"] = blocked
        if rtype == "script":
            ev["f"] = url.split("#", 1)[0][:2000] if self.conf.get("fullUrls") else _short_script(url)
        elif self.conf.get("fullUrls"):
            ev["f"] = url.split("#", 1)[0][:2000]
        self.add(tab, ev)

    def cookie(self, tab: "Tab", domain: str, name: str, purpose: str, who: str) -> None:
        rec = self.current(tab)
        key = f"{domain}\t{name}"
        if rec is None or key in rec._cookies:
            return
        rec._cookies.add(key)
        self.add(tab, {"k": "cookie", "h": domain.lstrip("."), "d": name[:64], "p": purpose, "w": who})

    def stripped(self, tab: "Tab", params: list[str]) -> None:
        tab.tm_pending.append({"k": "strip", "d": ", ".join(params[:12])})

    def loaded(self, tab: "Tab", ok: bool) -> None:
        rec = self.current(tab)
        if rec is None or rec.loaded_ms is not None:
            return
        rec.loaded_ms = rec.ms()
        rec.title = tab.title()[:200]
        self.add(tab, {"k": "load", "d": "ok" if ok else "failed"})

    def on_probe(self, tab: "Tab", payload: str) -> None:
        try:
            p = json.loads(payload)
        except ValueError:
            return
        if not isinstance(p, dict) or not isinstance(p.get("a"), str):
            return
        ev = {"k": "probe", "a": p["a"][:24], "s": str(p.get("s", ""))[:255].lower(), "d": str(p.get("d", ""))[:80]}
        if ev["a"] == "beacon" and ev["d"]:
            ev["h"] = ev["d"].lower()
        self.add(tab, ev)

    def download(self, tab: "Tab", host: str, name: str) -> None:
        """A link that turned out to be a download: Qt starts it as a main-frame
        request, which opened a fresh recording. Fold it back into the page's."""
        recs = self.recs.get(tab.id)
        if recs and len(recs) >= 2 and recs[-1].host == host and recs[-1].ms() < 5000 and len(recs[-1].events) <= 4:
            recs.pop()
        ext = name.rsplit(".", 1)[-1][:8].lower() if "." in name else ""
        self.add(tab, {"k": "dl", "h": host, "d": ext})

    def drop(self, tab_id: int) -> None:
        self.recs.pop(tab_id, None)

    def clear(self) -> None:
        self.recs.clear()

    # ------------------------------------------------------------ export
    def export(self, rec: Recording) -> str:
        default = Path.home() / f"prism-timemachine-{rec.site or 'page'}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(self.w, "Export recording", str(default), "JSON (*.json)")
        if not path:
            return ""
        data = {"prism": "time-machine", "version": 1, "meta": rec.meta(False), "hosts": rec.hosts,
                "events": rec.events, "protections": {k: v[0] for k, v in PROTECTIONS.items()},
                "note": "Metadata only: no page content, form input, cookie or storage values."}
        Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")
        return path


class TimeMachineBridge(QObject):
    """What ui/timemachine.js can call; lives in the privileged UI profile."""

    push = pyqtSignal(str, str)

    def __init__(self, window: "PrismWindow", tm: TimeMachine):
        super().__init__(window)
        self.w = window
        self.tm = tm
        self.selected: int | None = None        # recording id the user picked, None = live
        self._sent: tuple | None = None         # (tab id, rec id)
        self._count = 0
        self._hosts = 0
        self._timer = QTimer(self, interval=PUSH_MS)
        self._timer.timeout.connect(self.refresh)

    def send(self, topic: str, data) -> None:
        self.push.emit(topic, json.dumps(data, default=str))

    def start(self) -> None:
        self._sent = None
        self.selected = None
        self.send("opened", {})
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _target(self) -> tuple["Tab | None", Recording | None, bool]:
        tab = self.w.current()
        if tab is None:
            return None, None, False
        recs = self.tm.recs.get(tab.id) or deque()
        rec = next((r for r in recs if r.id == self.selected), None) if self.selected else None
        if rec is None:
            self.selected = None
            rec = recs[-1] if recs else None
        live = rec is not None and rec is recs[-1] and tab.url.scheme() in ("http", "https")
        return tab, rec, live

    def refresh(self) -> None:
        tab, rec, live = self._target()
        key = (tab.id if tab else None, rec.id if rec else None)
        if rec is None:
            if self._sent != key:
                self._sent = key
                self.send("empty", {"tab": tab.title() if tab else "", "settings": self.tm.conf})
            return
        if self._sent != key:
            self._sent = key
            self._count, self._hosts = len(rec.events), len(rec.hosts)
            recs = self.tm.recs.get(tab.id) or deque()
            self.send("full", {
                "meta": rec.meta(live), "hosts": rec.hosts, "events": rec.events,
                "recordings": [{"id": r.id, "origin": r.origin, "started": round(r.started * 1000),
                                "count": len(r.events)} for r in reversed(recs)],
                "protections": {k: list(v) for k, v in PROTECTIONS.items()},
                "env": self._env(tab), "settings": self.tm.conf,
            })
            return
        if len(rec.events) != self._count or len(rec.hosts) != self._hosts or live:
            new = rec.events[self._count:]
            self._count = len(rec.events)
            hosts = rec.hosts if len(rec.hosts) != self._hosts else {}
            self._hosts = len(rec.hosts)
            self.send("append", {"id": rec.id, "meta": rec.meta(live), "events": new, "hosts": hosts})

    def _env(self, tab: "Tab") -> dict:
        host = tab.url.host().lower()
        return {"dns": self.w.settings["dns"]["mode"] if self.w.doh else "off",
                "shield": not self.w.engine.shield_off_for(host),
                "js": getattr(tab, "js_enabled", True),
                "sandbox": tab.container.kind == "sandbox"}

    # ------------------------------------------------------------- slots
    @pyqtSlot()
    def ready(self) -> None:
        self._sent = None
        self.refresh()

    @pyqtSlot(str, str)
    def call(self, action: str, payload: str) -> None:
        try:
            p = json.loads(payload) if payload else {}
        except ValueError:
            p = {}
        if action == "close":
            self.w.toggle_time_machine(False)
        elif action == "select":
            rid = p.get("id")
            self.selected = int(rid) if rid else None
            self._sent = None
            self.refresh()
        elif action == "setting":
            key, value = p.get("key"), bool(p.get("value"))
            if key in ("probes", "fullUrls"):
                self.tm.conf[key] = value
                self.w.settings.save()
                if key == "probes":
                    self.w.install_probes()
                self.send("settings", self.tm.conf)
                self.w.bridge.toast.emit("Time Machine: applies from the next page load")
        elif action == "reload":
            tab = self.w.current()
            if tab:
                self.selected = None
                tab.view.reload()
        elif action == "export":
            _tab, rec, _live = self._target()
            if rec:
                path = self.tm.export(rec)
                if path:
                    self.w.bridge.toast.emit(f"recording exported to {path}")
