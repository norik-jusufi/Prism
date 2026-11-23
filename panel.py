"""PRISM panel backend: everything ui/panel.js can ask for.

The panel page talks to Python through one slot, call(action, payload_json),
and receives data on one signal, push(topic, json). Only the panel and the
toolbar (both local UI files in a separate, privileged profile) have this
bridge; websites never do.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from containers import CONTAINER_PRESETS
from designai import DIGEST_JS, HIGHLIGHT_JS, screenshot_png
from edition import EDITION, enabled
from memory import child_processes, process_memory
from siteintel import SECURITY_HEADERS, site_of
from storage import DNS_PROVIDERS, PERMISSION_TYPES
from tabs import APP_WORLD
from urls import NEWTAB_URL, resolve_input
from vault import VaultError, generate_password

if TYPE_CHECKING:
    from prism import PrismWindow, Tab

ALL_SECTIONS = ("site", "network", "source", "design", "api", "terminal", "memory",
                "containers", "permissions", "vault", "bookmarks")
# Sections named after an edition feature disappear with it (see edition.py).
SECTIONS = tuple(s for s in ALL_SECTIONS if enabled(s))
# Panel actions that belong to an edition feature: "vault.fill" -> "vault".
ACTION_FEATURES = {"vault": "vault", "term": "terminal"}
LIVE = {"site": 1, "network": 1, "memory": 2, "containers": 2, "design": 2}   # refresh period (s)

PAGE_META_JS = r"""(function () {
  var q = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var meta = q('meta').map(function (m) {
    return { name: m.getAttribute('name') || m.getAttribute('property') || m.getAttribute('http-equiv') || (m.getAttribute('charset') ? 'charset' : ''),
             content: m.getAttribute('content') || m.getAttribute('charset') || '' };
  }).filter(function (m) { return m.name; });
  var links = q('link[rel]').map(function (l) { return { rel: l.getAttribute('rel'), href: l.href, type: l.type || '' }; });
  var forms = q('form').map(function (f) {
    return { action: f.action, method: (f.method || 'get').toUpperCase(),
             password: !!f.querySelector('input[type=password]'), inputs: f.querySelectorAll('input,select,textarea').length };
  });
  return JSON.stringify({
    title: document.title, lang: document.documentElement.lang || '', charset: document.characterSet,
    doctype: document.doctype ? '<!DOCTYPE ' + document.doctype.name + '>' : '(none)',
    mode: document.compatMode, referrer: document.referrer, lastModified: document.lastModified,
    meta: meta, links: links, forms: forms,
    counts: { scripts: q('script').length, inlineScripts: q('script:not([src])').length, styles: q('link[rel=stylesheet],style').length,
              images: q('img').length, iframes: q('iframe').length, links: q('a[href]').length, elements: document.getElementsByTagName('*').length },
    iframes: q('iframe').slice(0, 30).map(function (f) { return f.src || '(inline)'; }),
    size: (document.documentElement.outerHTML || '').length
  });
})()"""

FILL_JS = r"""(function (user, pass) {
  function vis(el) { return el && el.offsetParent !== null && !el.disabled && !el.readOnly; }
  var pw = Array.prototype.slice.call(document.querySelectorAll('input[type=password]')).filter(vis)[0];
  if (!pw) return 'nofield';
  var scope = pw.form || document;
  var users = Array.prototype.slice.call(scope.querySelectorAll(
      'input[type=email],input[type=text],input[type=tel],input[autocomplete=username],input:not([type])')).filter(vis);
  var before = users.filter(function (el) { return el.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING; });
  var u = before[before.length - 1] || users[0];
  var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  function set(el, v) {
    el.focus(); setter.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  if (u && user) set(u, user);
  set(pw, pass);
  return 'ok';
})(%s, %s)"""


class PanelBridge(QObject):
    push = pyqtSignal(str, str)          # topic, JSON payload

    def __init__(self, window: "PrismWindow"):
        super().__init__(window)
        self.w = window
        self.section = "site"
        self._last: dict[str, str] = {}
        self._ticks = 0
        self._clip_timer = QTimer(self, singleShot=True, interval=20000)
        self._clip_timer.timeout.connect(self._clear_clipboard)
        self._clip_text = ""
        window.api.finished.connect(lambda res: self.push.emit("api", res))
        if window.terminal:
            window.terminal.output.connect(
                lambda text, stream: self.push.emit("term", json.dumps({"text": text, "stream": stream})))
            window.terminal.stateChanged.connect(lambda _k: self.send("termState", self.w.terminal.summary()))

    # ------------------------------------------------------------ plumbing
    def send(self, topic: str, data) -> None:
        self.push.emit(topic, json.dumps(data, default=str))

    def push_section(self, section: str, force: bool = True) -> None:
        if not self.w.panel_view.isVisible() and not force:
            return
        builder = getattr(self, f"_data_{section}", None)
        if builder is None:
            return
        try:
            data = json.dumps(builder(), default=str)
        except Exception as exc:  # noqa: BLE001 - never break the panel
            data = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        if not force and self._last.get(section) == data:
            return
        self._last[section] = data
        self.push.emit(section, data)

    def open(self, section: str, focus: bool = False) -> None:
        if section in SECTIONS:
            self.section = section
        elif self.section not in SECTIONS:
            self.section = SECTIONS[0]
        self.send("open", {"section": self.section, "focus": focus})
        self.push_section(self.section)

    def on_active_changed(self) -> None:
        if self.w.panel_view.isVisible() and self.section in ("site", "network", "source", "design"):
            self.push_section(self.section)

    def tick(self) -> None:
        self._ticks += 1
        if not self.w.panel_view.isVisible():
            return
        period = LIVE.get(self.section)
        if period and self._ticks % period == 0:
            self.push_section(self.section, force=False)

    def toast(self, text: str) -> None:
        self.send("toast", {"text": text})

    # --------------------------------------------------------------- slots
    @pyqtSlot()
    def ready(self) -> None:
        self.send("init", {
            "sections": SECTIONS,
            "edition": EDITION,
            "permissionTypes": {k: v[0] for k, v in PERMISSION_TYPES.items()},
            "dnsProviders": {k: v[0] for k, v in DNS_PROVIDERS.items()},
            "securityHeaders": SECURITY_HEADERS,
        })
        self.open(self.section)
        if self.w.terminal:
            self.send("termState", self.w.terminal.summary())

    @pyqtSlot(str)
    def setSection(self, section: str) -> None:
        if section in SECTIONS:
            self.section = section
            self.push_section(section)
            self.w.push_state()

    @pyqtSlot(str, str)
    def call(self, action: str, payload: str) -> None:
        try:
            p = json.loads(payload) if payload else {}
        except ValueError:
            p = {}
        feature = ACTION_FEATURES.get(action.split(".", 1)[0])
        if feature and not enabled(feature):
            self.toast("Not available in this edition of PRISM")
            return
        fn = getattr(self, "_do_" + action.replace(".", "_"), None)
        if fn is None:
            self.toast(f"Unknown action {action}")
            return
        try:
            fn(p)
        except VaultError as exc:
            self.send("vaultError", {"message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self.toast(f"{type(exc).__name__}: {exc}")

    # -------------------------------------------------------------- helpers
    @property
    def tab(self) -> "Tab":
        return self.w.current()

    def _web_tab(self) -> "Tab | None":
        t = self.tab
        return t if t and t.url.scheme() in ("http", "https") else None

    def _copy(self, text: str, secret: bool = False) -> None:
        QApplication.clipboard().setText(text)
        if secret:
            self._clip_text = text
            self._clip_timer.start()

    def _clear_clipboard(self) -> None:
        cb = QApplication.clipboard()
        if cb.text() == self._clip_text:
            cb.clear()
        self._clip_text = ""

    # ================================================================ SITE
    def _data_site(self) -> dict:
        t = self._web_tab()
        if t is None:
            return {"empty": True}
        url = t.url
        host = url.host().lower()
        site = site_of(host)
        rule = self.w.settings.scripts_for(site)
        perms = []
        for ptype, (label, _default) in PERMISSION_TYPES.items():
            site_rule = self.w.settings["sitePermissions"].get(site, {}).get(ptype)
            perms.append({"type": ptype, "label": label, "policy": self.w.settings.permission_policy(site, ptype),
                          "custom": bool(site_rule)})
        refused: dict[str, int] = {}
        for r in t.log.cookies_refused:
            refused[r["origin"]] = refused.get(r["origin"], 0) + 1
        vault = self.w.vault
        vault_entries = None
        if vault and vault.unlocked:
            vault_entries = [{"id": e["id"], "username": e["username"]} for e in self.w.vault.for_site(host)]
        return {
            "url": url.toString(), "host": host, "site": site, "title": t.title(),
            "container": t.container.info(),
            "shieldOn": not self.w.engine.shield_off_for(host),
            "blocked": self.w.engine.counts.get(host, 0),
            "trust": self.w.trust_for(t),
            "headersChecked": bool(t.headers),
            "cookies": sorted(self.w.site_cookies(t), key=lambda c: (c["purpose"], c["name"])),
            "refused": sorted(({"origin": k, "count": v} for k, v in refused.items()), key=lambda r: -r["count"]),
            "map": t.log.tracker_map(self.w.engine.is_tracker),
            "scripts": t.log.scripts(),
            "rule": rule,
            "jsEnabled": getattr(t, "js_enabled", True),
            "sandbox": t.container.kind == "sandbox", "sandboxJs": t.sandbox_js,
            "permissions": perms,
            "vault": {"unlocked": bool(vault and vault.unlocked), "exists": bool(vault and vault.exists),
                      "entries": vault_entries},
        }

    def _do_site_refresh(self, _p):
        t = self._web_tab()
        if t:
            self.w.headers.cache.pop(t.url.toString(QUrl.UrlFormattingOption.RemoveFragment), None)
            t.headers = None
            self.w.headers.fetch(t.url.toString(QUrl.UrlFormattingOption.RemoveFragment))
        self.push_section("site")

    def _set_rule(self, mutate, reload: bool = True):
        t = self._web_tab()
        if not t:
            return
        site = site_of(t.url.host())
        rule = self.w.settings.scripts_for(site)
        mutate(rule)
        self.w.settings.set_scripts(site, rule)
        if reload:
            t.view.reload()
        self.push_section("site")

    def _do_site_js(self, p):
        t = self._web_tab()
        if t and t.container.kind == "sandbox":
            self.w.toggle_sandbox_js()
            return
        self._set_rule(lambda r: r.update(js=bool(p.get("on"))))

    def _do_site_thirdParty(self, p):
        self._set_rule(lambda r: r.update(thirdParty="block" if p.get("block") else "allow"))

    def _do_site_blockHost(self, p):
        host = str(p.get("host", "")).lower()

        def mutate(r):
            hosts = set(r["blockedHosts"])
            (hosts.add if p.get("block") else hosts.discard)(host)
            r["blockedHosts"] = sorted(hosts)
        if host:
            self._set_rule(mutate)

    def _do_site_cookieDelete(self, p):
        t = self._web_tab()
        if t:
            self.w.delete_cookie(t, p.get("key", ""))
            self.push_section("site")

    def _do_site_cookiesClear(self, _p):
        t = self._web_tab()
        if t:
            for c in self.w.site_cookies(t):
                self.w.delete_cookie(t, c["key"])
            self.toast(f"Deleted cookies for {site_of(t.url.host())}")
            self.push_section("site")

    def _do_site_permission(self, p):
        t = self._web_tab()
        if t:
            self.w.settings.set_site_permission(site_of(t.url.host()), p["type"], p.get("policy"))
            self.push_section("site")

    def _do_site_shield(self, _p):
        self.w.toggle_shield()
        QTimer.singleShot(300, lambda: self.push_section("site"))

    # ============================================================= NETWORK
    def _data_network(self) -> dict:
        t = self._web_tab()
        s = self.w.settings
        DOH_PROXY = self.w.doh
        dns_running = None
        if DOH_PROXY:
            dns_running = {**DOH_PROXY.stats(), "template": DOH_PROXY.resolver.template,
                           "strict": DOH_PROXY.resolver.strict}
        entries = t.log.entries[-700:] if t else []
        reasons: dict[str, int] = {}
        for e in (t.log.entries if t else []):
            if e["blocked"]:
                reasons[e["blocked"]] = reasons.get(e["blocked"], 0) + 1
        return {
            "page": t.url.toString() if t else "", "entries": entries, "dropped": t.log.dropped if t else 0,
            "total": len(t.log.entries) if t else 0, "reasons": reasons,
            "protection": s["protection"], "custom": s["customBlocks"],
            "dns": s["dns"], "dnsRunning": dns_running,
            "lists": {"trackers": len(self.w.blocklist), "malware": len(self.w.blocklist.malware),
                      "sources": self.w.blocklist.sources, "securitySources": self.w.blocklist.security_sources},
            "allowedMalware": sorted(self.w.engine.malware_allow),
        }

    def _do_net_protection(self, p):
        key = p.get("key")
        if key in ("malware", "suspiciousScripts"):
            self.w.settings["protection"][key] = bool(p.get("on"))
            self.w.settings.save()
        self.push_section("network")

    def _do_net_customAdd(self, p):
        host = str(p.get("host", "")).strip().lower()
        host = QUrl(host if "://" in host else "http://" + host).host() or host
        if not host or "." not in host:
            self.toast("Enter a domain like ads.example.com")
            return
        lst = self.w.settings["customBlocks"]
        if host not in lst:
            lst.append(host)
            self.w.settings.save()
            self.w.engine.reload_custom()
            self.toast(f"Blocking {host} everywhere")
        self.push_section("network")

    def _do_net_customRemove(self, p):
        lst = self.w.settings["customBlocks"]
        if p.get("host") in lst:
            lst.remove(p["host"])
            self.w.settings.save()
            self.w.engine.reload_custom()
        self.push_section("network")

    def _do_net_dns(self, p):
        mode = p.get("mode") if p.get("mode") in ("off", "secure", "strict") else "off"
        provider = p.get("provider") if p.get("provider") in DNS_PROVIDERS else "cloudflare"
        self.w.settings["dns"].update(mode=mode, provider=provider)
        self.w.settings.save()
        self.toast("Encrypted DNS setting saved. Restart PRISM to apply it.")
        self.push_section("network")

    def _do_net_test(self, p):
        """Look one hostname up through the configured DoH provider."""
        import threading
        from dohproxy import DohResolver
        name = str(p.get("host", "example.com")).strip() or "example.com"
        provider = DNS_PROVIDERS.get(self.w.settings["dns"]["provider"], DNS_PROVIDERS["cloudflare"])

        def run():
            t0 = time.perf_counter()
            try:
                ips = DohResolver(provider[1], strict=True).resolve(name)
                res = {"ok": True, "host": name, "ips": ips, "ms": round((time.perf_counter() - t0) * 1000), "provider": provider[0]}
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "host": name, "error": str(exc), "provider": provider[0]}
            self.push.emit("dnsTest", json.dumps(res))
        threading.Thread(target=run, daemon=True).start()

    # ============================================================== SOURCE
    def _data_source(self) -> dict:
        t = self._web_tab()
        if not t:
            return {"empty": True}
        return {"url": t.url.toString(), "headers": t.headers, "resources": t.log.entries[-1500:]}

    def _do_source_load(self, _p):
        t = self._web_tab()
        if not t:
            self.send("source", {"empty": True})
            return
        url = t.url.toString()
        self.push_section("source")
        t.page.toHtml(lambda html, url=url: self.send("sourceHtml", {"url": url, "html": html[:3_000_000],
                                                                      "truncated": len(html) > 3_000_000}))
        t.page.runJavaScript(PAGE_META_JS, APP_WORLD,
                             lambda meta, url=url: self.send("sourceMeta", {"url": url, **(json.loads(meta) if meta else {})}))
        if not t.headers:
            self.w.headers.fetch(t.url.toString(QUrl.UrlFormattingOption.RemoveFragment))

    # ============================================================== DESIGN
    def _data_design(self) -> dict:
        t = self._web_tab()
        return {**self.w.design.info(), "current": {"url": t.url.toString(), "title": t.title()} if t else None,
                "sandbox": bool(t and t.container.kind == "sandbox")}

    def _do_design_review(self, p):
        """Measure the page, screenshot it, and send both to Claude (only on this explicit click)."""
        t = self._web_tab()
        if not t:
            self.toast("Open a web page first")
            return
        if t.container.kind == "sandbox":
            self.toast("Sandbox tabs are never sent anywhere. Open the page in a normal tab to review it.")
            return
        if self.w.design.busy:
            return
        url, title, focus = t.url.toString(), t.title(), str(p.get("focus", "")).strip()[:500]

        def got_digest(digest):
            if self.tab is not t or t.url.toString() != url:
                self.toast("The tab changed before it was measured. Try again.")
                return
            if not digest:
                self.toast("Couldn't measure this page (scripts may be off for it)")
                return
            try:
                shot = screenshot_png(t.view)
            except Exception as exc:  # noqa: BLE001
                self.toast(str(exc))
                return
            self.w.design.review(url, title, digest, shot, focus)
        t.page.runJavaScript(DIGEST_JS, APP_WORLD, got_digest)

    def _do_design_highlight(self, p):
        t = self._web_tab()
        sel = str(p.get("selector", ""))
        if not t or not sel:
            return
        if t.url.toString() != self.w.design.report.get("url"):
            self.toast("This issue is from another page")
            return
        t.page.runJavaScript(HIGHLIGHT_JS % json.dumps(sel), APP_WORLD,
                             lambda r: r == "ok" or self.toast("That element isn't on the page any more"))

    def _do_design_key(self, p):
        try:
            self.w.design.set_key(str(p.get("key", "")))
        except ValueError as exc:
            self.toast(str(exc))
            return
        self.toast("API key saved, encrypted with Windows DPAPI" if self.w.design.info()["canSave"]
                   else "API key kept in memory until PRISM closes")

    def _do_design_forgetKey(self, _p):
        self.w.design.forget_key()
        self.toast("API key forgotten")

    # ================================================================= API
    def _do_api_send(self, p):
        self.w.api.send(p)

    # ============================================================ TERMINAL
    def _do_term_run(self, p):
        self.w.terminal.run(str(p.get("line", "")))

    def _do_term_interrupt(self, _p):
        self.w.terminal.interrupt()

    def _do_term_shell(self, p):
        self.w.terminal.set_shell(p.get("shell", "cmd"))
        self.w.settings["terminal"]["shell"] = self.w.terminal.shell
        self.w.settings.save()

    def _do_term_cwd(self, p):
        self.w.terminal.run(f'cd "{p.get("path", "")}"')
        self.w.settings["terminal"]["cwd"] = self.w.terminal.cwd
        self.w.settings.save()

    # ============================================================== MEMORY
    def _data_memory(self) -> dict:
        tabs, pids = [], {}
        for t in self.w.tabs:
            pid = t.page.renderProcessPid() if not t.discarded else 0
            pids.setdefault(pid, []).append(t.id)
            tabs.append({"id": t.id, "title": t.title(), "url": t.url.toString(), "pid": pid,
                         "container": t.container.info(), "discarded": t.discarded,
                         "visible": self.w.pane_of(t) is not None, "active": t is self.w.current()})
        mem_cache: dict[int, dict | None] = {}

        def mem(pid):
            if pid not in mem_cache:
                mem_cache[pid] = process_memory(pid)
            return mem_cache[pid]
        for tab in tabs:
            m = mem(tab["pid"]) if tab["pid"] else None
            share = len(pids.get(tab["pid"], [])) if tab["pid"] else 0
            tab.update(memory=m, sharedWith=share)
        renderer_pids = {p for p in pids if p}
        procs = []
        for pr in child_processes():
            m = mem(pr["pid"])
            role = "Tab renderer" if pr["pid"] in renderer_pids else "Engine (GPU / network / utility)"
            procs.append({**pr, "memory": m, "role": role})
        main = process_memory(os.getpid())
        total = (main or {}).get("private", 0) + sum((p["memory"] or {}).get("private", 0) for p in procs)
        return {"tabs": tabs, "processes": procs, "main": main, "totalPrivate": total, "time": int(time.time())}

    def _do_mem_discard(self, p):
        t = self.w.tab_by_id(int(p.get("id", 0)))
        if t:
            self.w.discard_tab(t)
        QTimer.singleShot(800, lambda: self.push_section("memory"))

    def _do_mem_close(self, p):
        self.w.close_tab(int(p.get("id", 0)))
        QTimer.singleShot(800, lambda: self.push_section("memory"))

    def _do_mem_activate(self, p):
        self.w.switch_tab(int(p.get("id", 0)))

    # ========================================================== CONTAINERS
    def _data_containers(self) -> dict:
        rows = []
        presets = {cid for cid, _, _ in CONTAINER_PRESETS}
        for cid, name, color in CONTAINER_PRESETS:
            c = self.w.containers.get(cid)
            rows.append({"id": cid, "name": name, "color": color, "kind": "standard", "active": c is not None,
                         "remember": bool(self.w.settings["rememberLogins"].get(cid)),
                         "tabs": sum(1 for t in self.w.tabs if t.container.id == cid),
                         "cookies": len(c.cookies) if c else 0,
                         "sites": len({site_of(i["domain"].lstrip(".")) for i in c.cookies.values()}) if c else 0})
        for c in self.w.containers.values():
            if c.id not in presets:
                rows.append({**c.info(), "active": True, "tabs": sum(1 for t in self.w.tabs if t.container is c),
                             "cookies": len(c.cookies),
                             "sites": len({site_of(i["domain"].lstrip(".")) for i in c.cookies.values()})})
        cur = self.tab
        return {"containers": rows, "current": cur.container.info() if cur else None}

    def _do_ct_open(self, p):
        cid = p.get("id", "default")
        url = p.get("url")
        c = self.w.containers.get(cid) or self.w.container(cid)
        self.w.new_tab(resolve_input(url) if url else NEWTAB_URL, container=c, focus_address=not url)
        self.push_section("containers")

    def _do_ct_temp(self, _p):
        self.w.new_temp_session()
        self.push_section("containers")

    def _do_ct_sandbox(self, p):
        url = str(p.get("url", "")).strip()
        if url:
            self.w.open_sandbox(resolve_input(url))
        else:
            self.w.open_sandbox()
        self.push_section("containers")

    def _do_ct_move(self, p):
        t = self.tab
        if t:
            self.w.move_to_container(t, p.get("id", "default"))

    def _do_ct_closeAll(self, p):
        cid = p.get("id")
        for t in [t for t in self.w.tabs if t.container.id == cid]:
            self.w.close_tab(t.id)
        self.push_section("containers")

    def _do_ct_clear(self, p):
        c = self.w.containers.get(p.get("id"))
        if c:
            remembered = c.login_dir is not None
            self.w.clear_container(c)
            self.toast(f"Erased saved logins and site data for {c.name}" if remembered
                       else f"Cleared cookies and cache for {c.name}")
        self.push_section("containers")

    def _do_ct_remember(self, p):
        cid, on = str(p.get("id", "")), bool(p.get("on"))
        name = next((n for i, n, _ in CONTAINER_PRESETS if i == cid), None)
        if name is None:
            return
        self.w.set_remember_logins(cid, on)
        self.toast(f"{name} remembers logins now. Sign in once and you stay signed in." if on
                   else f"{name} forgets logins again. Its saved data was erased.")
        self.push_section("containers")

    # ========================================================= PERMISSIONS
    def _data_permissions(self) -> dict:
        s = self.w.settings
        pending = []
        for t in self.w.tabs:
            for pr in t.prompts:
                pending.append({**{k: v for k, v in pr.items() if k != "_perm"}, "tab": t.id, "tabTitle": t.title()})
        return {"types": [{"type": k, "label": v[0], "policy": s["permissionDefaults"].get(k, v[1])}
                          for k, v in PERMISSION_TYPES.items()],
                "sites": s["sitePermissions"], "pending": pending,
                "denied": self.w.engine.stats.perms_denied}

    def _do_perm_default(self, p):
        if p.get("type") in PERMISSION_TYPES and p.get("policy") in ("ask", "allow", "block"):
            self.w.settings["permissionDefaults"][p["type"]] = p["policy"]
            self.w.settings.save()
        self.push_section("permissions")

    def _do_perm_site(self, p):
        self.w.settings.set_site_permission(p.get("site", ""), p.get("type", ""), p.get("policy"))
        self.push_section("permissions")

    def _do_perm_clearSite(self, p):
        self.w.settings["sitePermissions"].pop(p.get("site", ""), None)
        self.w.settings.save()
        self.push_section("permissions")

    def _do_perm_answer(self, p):
        self.w.answer_permission(p.get("id", ""), bool(p.get("allow")), bool(p.get("remember")))

    # =============================================================== VAULT
    def _data_vault(self) -> dict:
        v = self.w.vault
        t = self._web_tab()
        host = t.url.host().lower() if t else ""
        data = {"exists": v.exists, "unlocked": v.unlocked, "host": host, "path": str(v.path)}
        if v.unlocked:
            data["entries"] = v.listing()
            data["forSite"] = [e["id"] for e in v.for_site(host)] if host else []
        return data

    def _do_vault_create(self, p):
        self.w.vault.create(p.get("password", ""))
        self.toast("Vault created. Don't lose the master password: it can't be recovered.")
        self.push_section("vault")

    def _do_vault_unlock(self, p):
        self.w.vault.unlock(p.get("password", ""))
        self.push_section("vault")

    def _do_vault_lock(self, _p):
        self.w.vault.lock()
        self.push_section("vault")

    def _do_vault_save(self, p):
        self.w.vault.upsert(p)
        self.toast("Saved")
        self.push_section("vault")

    def _do_vault_delete(self, p):
        self.w.vault.delete(p.get("id", ""))
        self.push_section("vault")

    def _do_vault_reveal(self, p):
        e = self.w.vault.get(p.get("id", ""))
        if e:
            self.send("vaultSecret", {"id": e["id"], "password": e["password"], "notes": e["notes"],
                                      "username": e["username"], "site": e["site"]})

    def _do_vault_copy(self, p):
        e = self.w.vault.get(p.get("id", ""))
        if e:
            field = "username" if p.get("field") == "username" else "password"
            self._copy(e[field], secret=field == "password")
            self.toast("Password copied: the clipboard clears in 20 s" if field == "password" else "Username copied")

    def _do_vault_fill(self, p):
        e = self.w.vault.get(p.get("id", ""))
        t = self._web_tab()
        if not e or not t:
            return
        if e["id"] not in {x["id"] for x in self.w.vault.for_site(t.url.host())}:
            self.toast(f"This login is for {e['site']}, not {t.url.host()}. Not filled.")
            return
        if t.url.scheme() != "https":
            self.toast("Refusing to fill a password into a page without HTTPS")
            return
        t.page.runJavaScript(FILL_JS % (json.dumps(e["username"]), json.dumps(e["password"])), APP_WORLD,
                             lambda r: self.toast("Filled" if r == "ok" else "No password field found on this page"))

    def _do_vault_generate(self, p):
        pw = generate_password(int(p.get("length", 20)), bool(p.get("symbols", True)))
        self.send("vaultGenerated", {"password": pw, "target": p.get("target", "")})

    def _do_vault_changePassword(self, p):
        self.w.vault.change_password(p.get("old", ""), p.get("new", ""))
        self.toast("Master password changed")
        self.push_section("vault")

    # =========================================================== BOOKMARKS
    def _data_bookmarks(self) -> dict:
        t = self._web_tab()
        return {"items": self.w.bookmarks.items,
                "current": {"title": t.title(), "url": t.url.toString()} if t else None}

    def _do_bm_save(self, p):
        self.w.bookmarks.upsert(p)
        self.push_section("bookmarks")

    def _do_bm_delete(self, p):
        self.w.bookmarks.delete(p.get("id", ""))
        self.push_section("bookmarks")

    def _do_bm_open(self, p):
        url = str(p.get("url", ""))
        if url:
            self.w.new_tab(resolve_input(url))

    def _do_copy(self, p):
        self._copy(str(p.get("text", "")))
        self.toast(p.get("label") or "Copied")

    def _do_tab_open(self, p):
        self._do_bm_open(p)
