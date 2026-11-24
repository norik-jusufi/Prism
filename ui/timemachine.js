/* PRISM Privacy Time Machine: replays a page's recorded activity.
   Python (timemachine.py) sends the recording over QWebChannel as "full",
   then "append" while the page keeps running. Everything shown is derived
   here from the events up to the playhead, so scrubbing is instant. */
(function () {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const app = $("#app");
  let tm = null;

  /* ------------------------------------------------------------ model */
  let R = null;                 // { meta, hosts, events, recordings, protections, env, settings }
  let recvAt = 0;               // performance.now() when meta.elapsed was measured
  let playhead = 0;             // ms since the recording started
  let playing = false;
  let follow = true;            // stick to the live edge
  let speed = 1;
  let lastIdx = -1;
  let trackStart = null;        // { i, e, why }
  let lastFrame = performance.now();
  let lastRender = 0;
  let rewinding = null;         // { from, start } while the rewind animation runs
  const SPEEDS = [0.25, 0.5, 1, 2, 4, 10, 25];

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  function fmt(ms, plus = true) {
    ms = Math.max(0, Math.round(ms));
    const m = Math.floor(ms / 60000), s = Math.floor(ms / 1000) % 60, x = ms % 1000;
    return (plus ? "T+" : "") + pad(m) + ":" + pad(s) + "." + pad(x, 3);
  }
  const short = (ms) => ms < 1000 ? `+${Math.round(ms)}ms` : `+${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`;
  const H = (h) => (R && R.hosts[h]) || { site: h, third: false, tracker: false };

  const PROT_ICON = { tracker: "⛨", malware: "☣", custom: "✋", sandbox: "▣", "script-rule": "⌘",
                      "third-party-script": "⧉", suspicious: "⚠", "cookie-wall": "◍", strip: "✂", permission: "⊘" };
  const REASON_TO_PROT = { tracker: "tracker", malware: "malware", custom: "custom", sandbox: "sandbox",
                           "script-rule": "script-rule", "third-party-script": "third-party-script", suspicious: "suspicious" };

  // probe api -> [label, what it means, severity, category]
  const API = {
    "canvas-read": ["Canvas fingerprint", "read back drawn pixels: a classic device fingerprint", "high", "fingerprint"],
    "webgl-id":    ["GPU fingerprint", "asked WebGL for the real GPU vendor and renderer", "high", "fingerprint"],
    "audio-fp":    ["Audio fingerprint", "created an OfflineAudioContext (audio-stack fingerprint)", "high", "fingerprint"],
    "font-probe":  ["Font probing", "measured text 60+ times to detect installed fonts", "high", "fingerprint"],
    "battery":     ["Battery status", "read battery level and charging state", "med", "fingerprint"],
    "devices":     ["Device list", "listed cameras, microphones and speakers", "high", "fingerprint"],
    "ua-hints":    ["Exact device details", "asked for high-entropy client hints", "med", "fingerprint"],
    "webrtc":      ["WebRTC connection", "can expose local network addresses", "med", "fingerprint"],
    "clipboard":   ["Clipboard read", "tried to read your clipboard", "high", "data"],
    "storage":     ["Local storage write", "", "low", "storage"],
    "idb":         ["IndexedDB database", "opened a browser database", "low", "storage"],
    "doc-cookie":  ["Cookie written by script", "", "low", "storage"],
    "beacon":      ["Beacon sent", "sent data in the background (sendBeacon)", "med", "send"],
    "listener":    ["Input watcher", "", "high", "watch"],
  };
  const FP = new Set(["canvas-read", "webgl-id", "audio-fp", "font-probe", "battery", "devices", "ua-hints", "webrtc", "clipboard"]);

  /* ----------------------------------------------------- classification */
  function isTracking(e) {
    const h = e.h ? H(e.h) : null;
    switch (e.k) {
      case "req": return !!(h && h.tracker);
      case "blk": return e.r === "tracker" || e.r === "malware" || !!(h && h.tracker);
      case "cookie": return e.p === "analytics" || e.p === "advertising";
      case "ckref": case "strip": return true;
      case "probe":
        if (FP.has(e.a) || e.a === "beacon") return true;
        return e.a === "listener" && !!(e.s && H(e.s).third);
      default: return false;
    }
  }
  function trackingWhy(e) {
    switch (e.k) {
      case "req": return `${e.h} (${e.ty})`;
      case "blk": return `${e.h} tried to load a ${e.ty}`;
      case "cookie": return `${e.w || e.d} cookie "${e.d}"`;
      case "ckref": return `${e.h} tried to set a cross-site cookie`;
      case "strip": return `tracking parameters in the link (${e.d})`;
      case "probe": return `${(API[e.a] || [e.a])[0].toLowerCase()}${e.s ? " by " + e.s : ""}`;
      default: return "";
    }
  }
  function findTrackStart() {
    trackStart = null;
    if (!R) return;
    for (let i = 0; i < R.events.length; i++) {
      if (isTracking(R.events[i])) { trackStart = { i, e: R.events[i], why: trackingWhy(R.events[i]) }; return; }
    }
  }

  // index of the first event after time t (events are in time order)
  function upto(t) {
    const ev = R.events;
    let lo = 0, hi = ev.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (ev[mid].t <= t) lo = mid + 1; else hi = mid; }
    return lo;
  }

  function duration() {
    if (!R) return 0;
    const last = R.events.length ? R.events[R.events.length - 1].t : 0;
    if (R.meta.live) return Math.max(last, R.meta.elapsed + (performance.now() - recvAt));
    return Math.max(last + 250, 1000);
  }

  /* ------------------------------------------------------- derivation */
  function derive(n) {
    const S = {
      servers: new Map(), scripts: new Map(), collect: [], prot: new Map(), sites: new Map(),
      signals: 0, inline: 0, trackers: new Set(), stopped: 0, loaded: null,
    };
    const collectSeen = new Map();
    const pushCollect = (key, item) => {
      const have = collectSeen.get(key);
      if (have) { have.n++; if (item.status === "through") have.status = "through"; return; }
      item.n = 1; collectSeen.set(key, item); S.collect.push(item);
    };
    const prot = (key, host, t) => {
      let p = S.prot.get(key);
      if (!p) S.prot.set(key, p = { n: 0, hosts: new Map(), last: 0 });
      p.n++; p.last = t;
      if (host) p.hosts.set(host, (p.hosts.get(host) || 0) + 1);
      S.stopped++;
    };
    for (let i = 0; i < n; i++) {
      const e = R.events[i];
      const h = e.h ? H(e.h) : null;
      if (e.k === "req" || e.k === "blk") {
        S.signals++;
        let s = S.servers.get(e.h);
        if (!s) S.servers.set(e.h, s = { host: e.h, site: h.site, third: h.third, tracker: h.tracker, req: 0, blk: 0,
                                          types: new Set(), first: e.t, reasons: new Set() });
        s.types.add(e.ty);
        let site = S.sites.get(h.site);
        if (!site) S.sites.set(h.site, site = { site: h.site, third: h.third, tracker: false, req: 0, blk: 0, first: e.t, last: e.t });
        site.last = e.t;
        if (h.tracker) { site.tracker = true; S.trackers.add(h.site); }
        if (e.k === "req") { s.req++; site.req++; } else {
          s.blk++; site.blk++; s.reasons.add(e.r);
          if (e.r === "tracker" || e.r === "malware") { site.tracker = true; S.trackers.add(h.site); }
          prot(REASON_TO_PROT[e.r] || e.r, e.h, e.t);
        }
        if (e.ty === "script") {
          let sc = S.scripts.get(e.h);
          if (!sc) S.scripts.set(e.h, sc = { host: e.h, third: h.third, tracker: h.tracker, files: new Set(), loaded: 0,
                                              blocked: 0, reasons: new Set(), first: e.t, apis: new Set() });
          if (e.f) sc.files.add(e.f);
          if (e.k === "req") sc.loaded++; else { sc.blocked++; sc.reasons.add(e.r); }
        }
        if (h.tracker || (e.k === "blk" && (e.r === "tracker" || e.r === "malware"))) {
          pushCollect("trk|" + h.site, { t: e.t, sev: "high", label: "Tracker contact", who: h.site,
            detail: `reports your visit to ${h.site}`, status: e.k === "blk" ? "stopped" : "through",
            by: e.k === "blk" ? prot_name(REASON_TO_PROT[e.r]) : "" });
        }
      } else if (e.k === "cookie") {
        const ad = e.p === "analytics" || e.p === "advertising";
        pushCollect("ck|" + e.h + "|" + e.d, { t: e.t, sev: ad ? "high" : "low", label: ad ? "Tracking cookie" : "Cookie stored",
          who: e.h, detail: `"${e.d}"` + (e.w ? ` · ${e.w}` : "") + (e.p && e.p !== "unknown" ? ` · ${e.p}` : ""),
          status: "stored" });
      } else if (e.k === "ckref") {
        pushCollect("ckref|" + e.h, { t: e.t, sev: "high", label: "Cross-site cookie", who: e.h,
          detail: "a third party tried to tag you across sites", status: "stopped", by: prot_name("cookie-wall") });
        prot("cookie-wall", e.h, e.t);
      } else if (e.k === "strip") {
        pushCollect("strip", { t: e.t, sev: "med", label: "Tracking parameters", who: "link",
          detail: e.d, status: "stopped", by: prot_name("strip") });
        prot("strip", "", e.t);
      } else if (e.k === "perm") {
        const st = e.r === "blocked" ? "stopped" : e.r === "allowed" ? "through" : "asked";
        pushCollect("perm|" + e.d, { t: e.t, sev: "med", label: "Permission: " + e.d, who: e.h,
          detail: st === "asked" ? "PRISM asked you" : st === "stopped" ? "denied" : "you allowed it",
          status: st, by: st === "stopped" ? prot_name("permission") : "" });
        if (e.r === "blocked") prot("permission", e.h, e.t);
      } else if (e.k === "probe") {
        const def = API[e.a] || [e.a, "", "low", "other"];
        const src = e.s || "inline / page";
        const third = !!(e.s && H(e.s).third);
        if (e.s) {
          const sc = S.scripts.get(e.s);
          if (sc) sc.apis.add(def[0]);
        }
        if (e.a === "listener") {
          if (!third) continue;                       // a site's own listeners are normal
          pushCollect("lst|" + e.s, { t: e.t, sev: "high", label: "Input watcher", who: src,
            detail: `third-party script listens to ${e.d}` , status: "observed", extra: e.d });
          continue;
        }
        let sev = def[2];
        if (def[3] === "storage" && third) sev = "med";
        const detail = def[3] === "storage" ? (e.d || def[1]) : def[1] + (e.a === "beacon" && e.d ? ` → ${e.d}` : "");
        pushCollect("prb|" + e.a + "|" + src + (def[3] === "storage" ? "|" + e.d : ""), { t: e.t, sev, label: def[0],
          who: src, detail, status: "observed" });
      } else if (e.k === "inline") {
        S.inline = e.d;
      } else if (e.k === "load") {
        S.loaded = e.t;
      }
    }
    // merge repeated input-watcher rows' details
    return S;
  }
  function prot_name(key) { return (R.protections[key] || [key])[0]; }

  /* ---------------------------------------------------------- render */
  let prevKeys = { collect: new Set(), servers: new Set(), scripts: new Set(), prot: new Map() };

  function renderAll(n) {
    const S = derive(n);
    renderVerdict(S, n);
    renderCounters(S);
    renderCollect(S);
    renderProt(S);
    renderServers(S);
    renderScripts(S);
    renderLog(n);
    MAP.update(S);
  }

  let lastAlert = false;
  function renderVerdict(S, n) {
    const v = $("#verdict");
    let cls, k, html;
    if (trackStart && trackStart.i < n) {
      cls = "alert"; k = "TRACKING";
      html = `TRACKING STARTED AT ${fmt(trackStart.e.t)}<small>${esc(trackStart.why)}` +
             (S.stopped ? ` · PRISM stopped ${S.stopped} attempt${S.stopped > 1 ? "s" : ""} so far` : "") + "</small>";
    } else if (trackStart) {
      cls = "pending"; k = "WATCHING";
      html = `NO TRACKING YET<small>tracking begins at ${fmt(trackStart.e.t)} · keep playing ▸</small>`;
    } else {
      cls = "calm"; k = "CLEAN";
      html = `NO TRACKING ACTIVITY RECORDED<small>${R.events.length > 1 ? "no trackers, fingerprinting or cross-site cookies seen on this page" : "waiting for the page to do something…"}</small>`;
    }
    v.className = "verdict " + cls;
    $("#v-k").textContent = k;
    $("#v-text").innerHTML = html;
    const alert = cls === "alert";
    if (alert && !lastAlert && playing) { void v.offsetWidth; v.classList.add("flash"); }
    lastAlert = alert;
  }

  function setCtr(id, val) {
    const el = $(id);
    const s = String(val);
    if (el.textContent !== s) {
      el.textContent = s;
      const box = el.parentElement;
      box.classList.remove("tick"); void box.offsetWidth; box.classList.add("tick");
    }
  }
  function renderCounters(S) {
    setCtr("#c-servers", [...S.servers.values()].filter((s) => s.third).length);
    setCtr("#c-scripts", S.scripts.size + (S.inline ? 1 : 0));
    setCtr("#c-collect", S.collect.length);
    setCtr("#c-trackers", S.trackers.size);
    setCtr("#c-stopped", S.stopped);
  }

  function statusTag(it) {
    switch (it.status) {
      case "stopped": return `<span class="tag g" title="${esc(it.by)}">stopped</span>`;
      case "through": return `<span class="tag r">got through</span>`;
      case "asked": return `<span class="tag a">asked you</span>`;
      case "stored": return `<span class="tag m">stored</span>`;
      default: return `<span class="tag v">observed</span>`;
    }
  }
  function renderCollect(S) {
    const el = $("#collect");
    if (!S.collect.length) {
      el.innerHTML = `<div class="empty"><b>Nothing collected yet.</b>Cookies, fingerprinting, storage, beacons,
        permission requests and tracker contacts appear here as the tape plays.</div>`;
      prevKeys.collect = new Set();
      return;
    }
    const order = { high: 0, med: 1, low: 2 };
    const items = S.collect.slice().sort((a, b) => order[a.sev] - order[b.sev] || a.t - b.t);
    const seen = new Set();
    el.innerHTML = items.map((it) => {
      const key = it.label + "|" + it.who + "|" + it.detail;
      seen.add(key);
      const isNew = !prevKeys.collect.has(key) && playing;
      return `<div class="row${isNew ? " new" : ""}">
        <i class="sev ${it.sev}" title="${it.sev} severity"></i>
        <div class="main"><div class="name">${esc(it.label)}${it.n > 1 ? ` <span class="muted">×${it.n}</span>` : ""}</div>
          <div class="sub"><b>${esc(it.who)}</b> · ${esc(it.detail)}${it.by ? ` · by ${esc(it.by)}` : ""}</div></div>
        <div style="text-align:right">${statusTag(it)}<div class="t">${short(it.t)}</div></div>
      </div>`;
    }).join("");
    prevKeys.collect = seen;
  }

  function renderProt(S) {
    const el = $("#prot");
    const keys = Object.keys(R.protections);
    const rows = keys.map((k) => ({ k, p: S.prot.get(k) })).sort((a, b) => (b.p ? b.p.n : 0) - (a.p ? a.p.n : 0));
    const html = rows.map(({ k, p }) => {
      const [name, desc] = R.protections[k];
      const n = p ? p.n : 0;
      const top = p ? [...p.hosts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map((x) => x[0]).join(", ") : "";
      const was = prevKeys.prot.get(k) || 0;
      const hit = n > was && playing;
      return `<div class="prot${n ? " on" : ""}${hit ? " hit" : ""}">
        <div class="ico">${PROT_ICON[k] || "◆"}</div>
        <div class="name">${esc(name)}</div><div class="n">${n}</div>
        <div class="sub">${n ? esc(top || desc) : esc(desc) + " · standing by"}</div>
      </div>`;
    }).join("");
    const env = R.env || {};
    const always = `<div class="prot-sep">ALWAYS ON</div>
      <div class="prot on"><div class="ico">⇄</div><div class="name">Do Not Track + Global Privacy Control</div>
        <div class="n">${S.signals}</div><div class="sub">opt-out signal sent with every request</div></div>
      <div class="prot${env.dns && env.dns !== "off" ? " on" : ""}"><div class="ico">⌬</div><div class="name">Encrypted DNS</div>
        <div class="n">${env.dns && env.dns !== "off" ? "on" : "off"}</div>
        <div class="sub">${env.dns && env.dns !== "off" ? "lookups hidden from your network (" + esc(env.dns) + ")" : "turn on in Panel → Network"}</div></div>
      <div class="prot${env.shield ? " on" : ""}"><div class="ico">⛨</div><div class="name">Shield for this site</div>
        <div class="n">${env.shield ? "on" : "off"}</div><div class="sub">${env.shield ? "blocking ads & trackers" : "switched off for this site"}</div></div>`;
    el.innerHTML = html + always;
    prevKeys.prot = new Map(rows.map(({ k, p }) => [k, p ? p.n : 0]));
  }

  function renderServers(S) {
    const el = $("#servers");
    const list = [...S.servers.values()].sort((a, b) => a.first - b.first);
    if (!list.length) { el.innerHTML = `<div class="empty"><b>No connections yet.</b></div>`; return; }
    const seen = new Set();
    el.innerHTML = list.slice(0, 250).map((s) => {
      seen.add(s.host);
      const isNew = !prevKeys.servers.has(s.host) && playing;
      const kind = s.tracker ? `<span class="tag r">tracker</span>` : s.third ? `<span class="tag c">3rd party</span>` : `<span class="tag g">1st party</span>`;
      const stat = s.blk && !s.req ? `<span class="tag g">all stopped</span>` : s.blk ? `<span class="tag a">${s.blk} stopped</span>` : "";
      return `<div class="row${isNew ? " new" : ""}">
        <span class="t">${short(s.first)}</span>
        <div class="main"><div class="name">${esc(s.host)}</div>
          <div class="sub">${s.req + s.blk} request${s.req + s.blk > 1 ? "s" : ""} · ${esc([...s.types].slice(0, 4).join(", "))}</div></div>
        <div class="tags" style="justify-content:flex-end">${kind}${stat}</div>
      </div>`;
    }).join("") + (list.length > 250 ? `<div class="empty">+ ${list.length - 250} more</div>` : "");
    prevKeys.servers = seen;
  }

  function renderScripts(S) {
    const el = $("#scripts");
    const list = [...S.scripts.values()].sort((a, b) => (b.third - a.third) || a.first - b.first);
    if (!list.length && !S.inline) { el.innerHTML = `<div class="empty"><b>No scripts yet.</b></div>`; return; }
    const seen = new Set();
    let html = list.map((s) => {
      seen.add(s.host);
      const isNew = !prevKeys.scripts.has(s.host) && playing;
      const st = s.loaded && !s.blocked ? `<span class="tag ${s.tracker ? "r" : "c"}">ran</span>`
        : !s.loaded ? `<span class="tag g" title="${esc([...s.reasons].map(prot_name).join(", "))}">stopped</span>`
        : `<span class="tag a">partly stopped</span>`;
      const files = [...s.files].slice(0, 3).map((f) => f.length > 40 ? f.slice(0, 38) + "…" : f).join(", ");
      const apis = [...s.apis].slice(0, 5).map((a) => `<span class="tag v">${esc(a)}</span>`).join("");
      return `<div class="row${isNew ? " new" : ""}">
        <span class="t">${short(s.first)}</span>
        <div class="main"><div class="name">${esc(s.host)} ${s.third ? "" : `<span class="muted">(own)</span>`}</div>
          <div class="sub">${esc(files || "script")}${s.loaded + s.blocked > 1 ? ` · ${s.loaded + s.blocked} files` : ""}</div>
          ${apis ? `<div class="tags">${apis}</div>` : ""}</div>
        <div>${st}</div>
      </div>`;
    }).join("");
    if (S.inline) html += `<div class="row"><span class="t">page</span><div class="main"><div class="name">${S.inline} inline script${S.inline > 1 ? "s" : ""}</div>
        <div class="sub">code embedded in the page itself</div></div><div><span class="tag m">ran</span></div></div>`;
    el.innerHTML = html;
    prevKeys.scripts = seen;
  }

  function logLine(e) {
    const h = e.h ? H(e.h) : null;
    const ts = `<span class="ts">[${fmt(e.t, false)}]</span> `;
    switch (e.k) {
      case "nav": return ts + `<span class="kd k-sys">OPEN</span> ${esc(R.meta.origin)} <span class="why">· recording started</span>`;
      case "load": return ts + `<span class="kd k-sys">LOAD</span> page ${e.d === "ok" ? "finished loading" : "failed to load"}`;
      case "req": return ts + `<span class="kd ${h.tracker ? "k-blk" : h.third ? "k-3p" : "k-req"}">${h.tracker ? "TRK" : "GET"}</span> ${esc(e.ty.padEnd(10))} ${esc(e.h)}${e.f ? ` <span class="why">${esc(e.f)}</span>` : ""}`;
      case "blk": return ts + `<span class="kd k-blk">BLOCK</span> ${esc(e.ty.padEnd(10))} ${esc(e.h)} <span class="why">← ${esc(prot_name(REASON_TO_PROT[e.r] || e.r))}</span>`;
      case "cookie": return ts + `<span class="kd k-col">COOKIE</span> ${esc(e.h)} set "${esc(e.d)}"${e.p && e.p !== "unknown" ? ` <span class="why">(${esc(e.p)})</span>` : ""}`;
      case "ckref": return ts + `<span class="kd k-blk">DENY</span> cross-site cookie from ${esc(e.h)} <span class="why">← cookie wall</span>`;
      case "strip": return ts + `<span class="kd k-col">STRIP</span> removed ${esc(e.d)} <span class="why">← link cleaner</span>`;
      case "perm": return ts + `<span class="kd k-col">PERM</span> ${esc(e.h)} wants ${esc(e.d)} <span class="why">→ ${esc(e.r)}</span>`;
      case "probe": return ts + `<span class="kd k-prb">PROBE</span> ${esc((API[e.a] || [e.a])[0])} <span class="why">by ${esc(e.s || "page")}${e.d ? " · " + esc(e.d) : ""}</span>`;
      case "dl": return ts + `<span class="kd k-sys">FILE</span> download${e.d ? " (." + esc(e.d) + ")" : ""} from ${esc(e.h)}`;
      case "inline": return ts + `<span class="kd k-sys">SCAN</span> ${e.d} inline script${e.d > 1 ? "s" : ""} in the page`;
      default: return ts + esc(e.k);
    }
  }
  function renderLog(n) {
    const el = $("#log");
    const from = Math.max(0, n - 300);
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.innerHTML = (from ? `<div class="why">… ${from} earlier events</div>` : "") +
      R.events.slice(from, n).map((e) => `<div>${logLine(e)}</div>`).join("") + `<div><span class="cursor"></span></div>`;
    if (atBottom || playing) el.scrollTop = el.scrollHeight;
  }

  /* ------------------------------------------------------ network map */
  const MAP = (() => {
    const cv = $("#map");
    const ctx = cv.getContext("2d");
    let nodes = new Map();      // site -> node
    let S = null;
    function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967295; }
    function update(state) {
      S = state;
      const sites = [...S.sites.values()].filter((s) => s.third).sort((a, b) => a.first - b.first);
      const next = new Map();
      sites.forEach((s, i) => {
        const old = nodes.get(s.site);
        const ring = i < 7 ? 0 : i < 19 ? 1 : 2;
        // golden-angle spacing: neighbours in time never land on top of each other
        next.set(s.site, { ...s, ring, angle: i * 2.39996 + 0.4, born: old ? old.born : performance.now(), idx: i });
      });
      nodes = next;
    }
    function resize() {
      const r = { width: cv.clientWidth, height: cv.clientHeight };   // layout size: ignores the power-on transform
      const dpr = window.devicePixelRatio || 1;
      if (cv.width !== Math.round(r.width * dpr) || cv.height !== Math.round(r.height * dpr)) {
        cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return r;
    }
    function draw(now) {
      if (!R) return;
      const r = resize();
      const W = r.width, Hh = r.height;
      ctx.clearRect(0, 0, W, Hh);
      if (W < 20 || Hh < 20) return;
      const cx = W / 2, cy = Hh / 2;
      // the map fills the card: an ellipse, not a circle
      const rx = Math.max(60, W / 2 - 80), ry = Math.max(40, Hh / 2 - 22);
      const RING = [0.46, 0.73, 0.98];
      ctx.lineWidth = 1;
      RING.forEach((f, i) => {
        ctx.strokeStyle = `rgba(54,245,155,${0.10 - i * 0.025})`;
        ctx.beginPath(); ctx.ellipse(cx, cy, rx * f, ry * f, 0, 0, Math.PI * 2); ctx.stroke();
      });
      const sweep = (now / 2600) % (Math.PI * 2) * (playing ? 1 : 0.25);
      const grad = ctx.createConicGradient ? ctx.createConicGradient(sweep, cx, cy) : null;
      if (grad) {
        grad.addColorStop(0, "rgba(54,245,155,.16)"); grad.addColorStop(0.08, "rgba(54,245,155,0)"); grad.addColorStop(1, "rgba(54,245,155,0)");
        ctx.fillStyle = grad; ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); ctx.fill();
      }
      const pos = (n) => {
        const f = RING[n.ring] * (0.94 + hash(n.site) * 0.1);
        return [cx + Math.cos(n.angle) * rx * f, cy + Math.sin(n.angle) * ry * f];
      };
      // edges
      for (const n of nodes.values()) {
        const [x, y] = pos(n);
        const blockedOnly = n.blk && !n.req;
        ctx.strokeStyle = n.tracker ? "rgba(255,95,109,.28)" : "rgba(79,214,255,.18)";
        ctx.setLineDash(blockedOnly ? [3, 4] : []);
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke();
      }
      ctx.setLineDash([]);
      // packets: events in the last 700ms of tape time travel along their edge
      if (S) {
        const n = upto(playhead);
        for (let i = n - 1, c = 0; i >= 0 && c < 140; i--, c++) {
          const e = R.events[i];
          const age = playhead - e.t;
          if (age > 700) break;
          if ((e.k !== "req" && e.k !== "blk") || !e.h) continue;
          const node = nodes.get(H(e.h).site);
          if (!node) continue;
          const [x, y] = pos(node);
          let f = age / 700;
          const blocked = e.k === "blk";
          if (blocked) f = Math.min(f, 0.55);
          const px = cx + (x - cx) * f, py = cy + (y - cy) * f;
          ctx.fillStyle = blocked ? "#ff5f6d" : node.tracker ? "#ff8a94" : "#4fd6ff";
          ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 8;
          ctx.beginPath(); ctx.arc(px, py, blocked ? 3 : 2.2, 0, Math.PI * 2); ctx.fill();
          if (blocked && age / 700 > 0.55) {
            const k = Math.min(1, (age / 700 - 0.55) / 0.45);
            ctx.strokeStyle = `rgba(255,95,109,${1 - k})`; ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.arc(px, py, 3 + k * 9, 0, Math.PI * 2); ctx.stroke(); ctx.lineWidth = 1;
          }
          ctx.shadowBlur = 0;
        }
      }
      // nodes
      ctx.font = "10.5px " + getComputedStyle(document.body).fontFamily;
      const labelled = [...nodes.values()].sort((a, b) => (b.req + b.blk) - (a.req + a.blk)).slice(0, 14);
      const showLabel = new Set(labelled.map((n) => n.site));
      for (const n of nodes.values()) {
        const [x, y] = pos(n);
        const grow = Math.max(0, Math.min(1, (now - n.born) / 450));
        const size = (3.5 + Math.min(7, Math.log2(1 + n.req + n.blk) * 1.6)) * (0.3 + 0.7 * grow);
        const blockedOnly = n.blk && !n.req;
        const col = n.tracker ? "#ff5f6d" : "#4fd6ff";
        const hot = playhead - n.last < 500;
        ctx.shadowColor = col; ctx.shadowBlur = hot ? 16 : 6;
        if (blockedOnly) {
          ctx.strokeStyle = col; ctx.setLineDash([2, 2]);
          ctx.beginPath(); ctx.arc(x, y, size, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
        } else {
          ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, size, 0, Math.PI * 2); ctx.fill();
        }
        ctx.shadowBlur = 0;
        if (grow < 1) {
          ctx.strokeStyle = `rgba(255,255,255,${1 - grow})`;
          ctx.beginPath(); ctx.arc(x, y, size + 10 * grow, 0, Math.PI * 2); ctx.stroke();
        }
        if (showLabel.has(n.site)) {
          ctx.fillStyle = n.tracker ? "#ffb3ba" : "#a9c9b5";
          const right = x >= cx;                       // labels point away from the centre
          ctx.textAlign = right ? "left" : "right";
          ctx.fillText(n.site.length > 24 ? n.site.slice(0, 22) + "…" : n.site, x + (right ? size + 5 : -size - 5), y + 3.5);
        }
      }
      // center: the site itself
      const pulse = 1 + Math.sin(now / 300) * 0.06;
      ctx.shadowColor = "#36f59b"; ctx.shadowBlur = 20;
      ctx.fillStyle = "#36f59b";
      ctx.beginPath(); ctx.arc(cx, cy, 9 * pulse, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(54,245,155,.5)";
      ctx.beginPath(); ctx.arc(cx, cy, 15 * pulse, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = "#e8f5ec";
      ctx.textAlign = "center";
      ctx.font = "bold 11.5px " + getComputedStyle(document.body).fontFamily;
      ctx.fillText(R.meta.site || R.meta.host, cx, cy + 30);
      if (!nodes.size) {
        ctx.fillStyle = "#5f8270"; ctx.font = "11px " + getComputedStyle(document.body).fontFamily;
        ctx.fillText("no third-party contact yet", cx, cy + 48);
      }
    }
    return { update, draw };
  })();

  /* --------------------------------------------------------- timeline */
  const TL = (() => {
    const cv = $("#tl");
    const ctx = cv.getContext("2d");
    const tip = $("#tl-tip");
    let bins = null, binsFor = "";
    function color(e) {
      const h = e.h ? H(e.h) : null;
      if (e.k === "blk" || e.k === "ckref") return 0;                   // stopped (red)
      if (e.k === "probe" || e.k === "cookie" || e.k === "strip" || e.k === "perm") return 1;  // collection
      if (h && h.tracker) return 0;
      if (h && h.third) return 2;
      return 3;
    }
    const COLS = ["#ff5f6d", "#b48cff", "#4fd6ff", "#1fa866"];
    function compute(W, dur) {
      const key = W + "|" + R.events.length + "|" + Math.round(dur / 200);
      if (key === binsFor) return;
      binsFor = key;
      const nb = Math.max(1, Math.floor(W / 3));
      bins = Array.from({ length: nb }, () => [0, 0, 0, 0]);
      for (const e of R.events) {
        const b = Math.min(nb - 1, Math.floor(e.t / dur * nb));
        bins[b][color(e)]++;
      }
    }
    function draw() {
      if (!R) return;
      const r = { width: cv.clientWidth, height: cv.clientHeight };
      const dpr = window.devicePixelRatio || 1;
      if (cv.width !== Math.round(r.width * dpr) || cv.height !== Math.round(r.height * dpr)) {
        cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const W = r.width, Hh = r.height;
      const dur = duration();
      compute(W, dur);
      ctx.clearRect(0, 0, W, Hh);
      // seconds grid
      const step = dur > 60000 ? 10000 : dur > 20000 ? 5000 : dur > 6000 ? 1000 : 500;
      ctx.fillStyle = "rgba(95,130,112,.9)"; ctx.font = "9.5px " + getComputedStyle(document.body).fontFamily;
      for (let t = 0; t <= dur; t += step) {
        const x = t / dur * W;
        ctx.fillStyle = "rgba(54,245,155,.10)"; ctx.fillRect(x, 0, 1, Hh);
        ctx.fillStyle = "rgba(95,130,112,.9)"; ctx.fillText((t / 1000).toFixed(step < 1000 ? 1 : 0) + "s", x + 3, Hh - 4);
      }
      // density bars
      const max = Math.max(1, ...bins.map((b) => b[0] + b[1] + b[2] + b[3]));
      const bw = W / bins.length;
      const scale = (Hh - 18) / Math.sqrt(max);
      const px = playhead / dur * W;
      bins.forEach((b, i) => {
        let y = Hh - 14;
        const x = i * bw;
        const past = x <= px;
        for (let c = 0; c < 4; c++) {
          if (!b[c]) continue;
          const tot = b[0] + b[1] + b[2] + b[3];
          const h = Math.sqrt(tot) * scale * (b[c] / tot);
          ctx.fillStyle = COLS[c];
          ctx.globalAlpha = past ? 0.95 : 0.25;
          ctx.fillRect(x, y - h, Math.max(1, bw - 1), h);
          y -= h;
        }
      });
      ctx.globalAlpha = 1;
      // markers
      const mark = (t, col, label) => {
        const x = t / dur * W;
        ctx.fillStyle = col; ctx.fillRect(x, 0, 1.5, Hh - 14);
        ctx.font = "bold 9.5px " + getComputedStyle(document.body).fontFamily;
        const w = ctx.measureText(label).width + 8;
        const lx = Math.min(W - w, x + 1);
        ctx.fillRect(lx, 0, w, 13);
        ctx.fillStyle = "#020604"; ctx.fillText(label, lx + 4, 10);
      };
      if (R.meta.loaded != null) mark(R.meta.loaded, "#36f59b", "LOADED");
      if (trackStart) mark(trackStart.e.t, "#ff5f6d", "TRACKING");
      // playhead
      ctx.fillStyle = "rgba(54,245,155,.08)"; ctx.fillRect(0, 0, px, Hh);
      ctx.shadowColor = "#e8f5ec"; ctx.shadowBlur = 10;
      ctx.fillStyle = "#e8f5ec"; ctx.fillRect(px - 1, 0, 2, Hh);
      ctx.shadowBlur = 0;
      ctx.beginPath(); ctx.moveTo(px - 6, 0); ctx.lineTo(px + 6, 0); ctx.lineTo(px, 7); ctx.fill();
    }
    let dragging = false;
    const at = (ev) => {
      const r = cv.getBoundingClientRect();
      return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)) * duration();
    };
    cv.parentElement.addEventListener("mousedown", (ev) => { if (!R) return; dragging = true; stopRewind(); seek(at(ev), true); });
    window.addEventListener("mousemove", (ev) => {
      if (!R) return;
      const r = cv.getBoundingClientRect();
      const inside = ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom;
      if (dragging) seek(at(ev), true);
      tip.hidden = !(inside || dragging);
      if (!tip.hidden) { tip.textContent = fmt(at(ev)); tip.style.left = Math.max(40, Math.min(r.width - 40, ev.clientX - r.left)) + "px"; }
    });
    window.addEventListener("mouseup", () => { dragging = false; });
    return { draw };
  })();

  /* --------------------------------------------------------- playback */
  function seek(t, user) {
    const dur = duration();
    playhead = Math.max(0, Math.min(dur, t));
    if (user) follow = R && R.meta.live && dur - playhead < 120;
  }
  function setPlaying(on) {
    playing = on;
    const b = $("#p-play");
    b.textContent = on ? "❚❚" : "▶";
    if (on && duration() - playhead < 50 && !(R && R.meta.live)) playhead = 0;   // replay from the top
  }
  function autoSpeed() {
    const d = duration();
    const want = d / 9000;           // replay the whole tape in ~9 s
    return SPEEDS.reduce((best, s) => Math.abs(Math.log(s / want)) < Math.abs(Math.log(best / want)) ? s : best, 1);
  }
  function setSpeed(s) {
    speed = s;
    for (const b of $("#speeds").children) b.classList.toggle("on", +b.dataset.s === s);
  }
  $("#speeds").innerHTML = SPEEDS.map((s) => `<button data-s="${s}">${s < 1 ? s : s + "×"}</button>`).join("");
  $("#speeds").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setSpeed(+b.dataset.s); });

  function rewind(thenPlay) {
    if (!R) return;
    rewinding = { from: playhead, start: performance.now(), thenPlay };
    playing = false; follow = false;
    $("#p-play").textContent = "▶";
    $("#rw").hidden = false;
    app.classList.add("rewinding");
    if (window.prismSound) window.prismSound("rewind");
  }
  function stopRewind() {
    if (!rewinding) return;
    rewinding = null;
    $("#rw").hidden = true;
    app.classList.remove("rewinding");
  }

  function frame(now) {
    try { step(now); } catch (err) { console.error(err); }     // never let one bad frame stop the tape
    requestAnimationFrame(frame);
  }
  function step(now) {
    const dt = Math.max(0, now - lastFrame);
    lastFrame = now;
    if (R) {
      const dur = duration();
      if (rewinding) {
        const k = Math.min(1, (now - rewinding.start) / 900);
        playhead = rewinding.from * (1 - (1 - Math.pow(1 - k, 3)));
        if (k >= 1) {
          const then = rewinding.thenPlay;
          stopRewind();
          playhead = 0;
          if (then) { setSpeed(autoSpeed()); setPlaying(true); }
        }
      } else if (playing) {
        playhead += dt * speed;
        if (playhead >= dur) {
          playhead = dur;
          if (R.meta.live) { follow = true; setPlaying(false); }
          else setPlaying(false);
        }
      } else if (follow && R.meta.live) {
        playhead = dur;
      }
      const n = upto(playhead);
      // Panels are rebuilt from scratch: ~11 times a second is plenty while the tape runs.
      if (n !== lastIdx && (!(playing || rewinding) || now - lastRender > 90)) { lastIdx = n; lastRender = now; renderAll(n); }
      $("#clk").textContent = fmt(playhead);
      $("#dur").textContent = "/ " + fmt(dur, false);
      const live = $("#p-live");
      live.classList.toggle("on", !!(R.meta.live && follow && !playing));
      live.classList.toggle("off-air", !R.meta.live);
      TL.draw();
      MAP.draw(now);
    }
  }

  /* ------------------------------------------------------------- data */
  function setSettings(s) {
    $("#s-probes").checked = !!s.probes;
    $("#s-full").checked = !!s.fullUrls;
  }

  function loadFull(d, isNewTape) {
    R = d;
    recvAt = performance.now();
    app.classList.remove("empty");
    $("#nosignal").hidden = true;
    lastIdx = -1;
    prevKeys = { collect: new Set(), servers: new Set(), scripts: new Set(), prot: new Map() };
    findTrackStart();
    setSettings(d.settings || {});
    const m = d.meta;
    $("#t-origin").textContent = m.url || m.origin;
    $("#t-origin").title = m.url || m.origin;
    const started = new Date(m.started);
    $("#t-meta").textContent = `${m.title ? m.title + " · " : ""}recorded ${started.toLocaleTimeString()} · ${m.container}` +
      (m.dropped ? ` · ${m.dropped} events over the limit` : "");
    const badge = $("#rec-badge");
    badge.className = "rec" + (m.live ? "" : " tape");
    badge.lastChild.textContent = m.live ? "REC" : "TAPE";
    $("#tapes").innerHTML = d.recordings.map((r, i) =>
      `<option value="${r.id}"${r.id === m.id ? " selected" : ""}>${i === 0 ? "● " : ""}${esc(r.origin.replace(/^https?:\/\//, ""))} · ${new Date(r.started).toLocaleTimeString()} · ${r.count} ev</option>`).join("");
    if (isNewTape) {
      playhead = duration();
      follow = !!m.live;
      rewind(true);
    }
  }

  function append(d) {
    if (!R || d.id !== R.meta.id) return;
    const wasTrack = trackStart;
    if (d.hosts && Object.keys(d.hosts).length) R.hosts = d.hosts;
    if (d.events.length) R.events.push(...d.events);
    R.meta = d.meta;
    recvAt = performance.now();
    if (!wasTrack) findTrackStart();
    lastIdx = -1;
  }

  function showEmpty(d) {
    R = null;
    app.classList.add("empty");
    $("#nosignal").hidden = false;
    $("#ns-tab").textContent = d.tab || "this tab";
    $("#t-origin").textContent = "—";
    $("#t-meta").textContent = "";
    setSettings(d.settings || {});
  }

  /* ------------------------------------------------------------- boot */
  const BOOT = [
    ["> prism tm --mount current-tab", ""],
    ["  loading flight recorder", "ok"],
    ["  decrypting session tape (memory only)", "ok"],
    ["  indexing network events", "ok"],
    ["  metadata filter: no content, no form input, no values", "ok"],
    ["  spinning up timeline", "ok"],
  ];
  let booted = false;
  function boot() {
    const pre = $("#boot-text");
    let i = 0;
    const step = () => {
      if (i >= BOOT.length) { setTimeout(() => { app.classList.remove("booting"); booted = true; }, 120); return; }
      const [line, st] = BOOT[i++];
      pre.innerHTML += esc(line) + (st ? ` <span class="dim">${".".repeat(Math.max(2, 52 - line.length))}</span> <span class="ok">[${st}]</span>` : "") + "\n";
      setTimeout(step, i === 1 ? 160 : 70);
    };
    step();
  }
  window.addEventListener("keydown", () => { if (!booted) { app.classList.remove("booting"); booted = true; } });

  /* --------------------------------------------------------- controls */
  $("#p-play").onclick = () => { stopRewind(); follow = false; setPlaying(!playing); };
  $("#p-start").onclick = () => rewind(false);
  $("#p-back").onclick = () => { stopRewind(); seek(playhead - 1000, true); };
  $("#p-fwd").onclick = () => { stopRewind(); seek(playhead + 1000, true); };
  $("#p-end").onclick = () => { stopRewind(); setPlaying(false); seek(duration(), true); follow = !!(R && R.meta.live); };
  $("#p-live").onclick = () => { if (R && R.meta.live) { stopRewind(); setPlaying(false); follow = true; } };
  $("#b-close").onclick = () => tm && tm.call("close", "");
  $("#b-export").onclick = () => tm && tm.call("export", "");
  $("#b-reload").onclick = () => tm && tm.call("reload", "");
  $("#tapes").onchange = (e) => tm && tm.call("select", JSON.stringify({ id: +e.target.value }));
  $("#s-probes").onchange = (e) => tm && tm.call("setting", JSON.stringify({ key: "probes", value: e.target.checked }));
  $("#s-full").onchange = (e) => tm && tm.call("setting", JSON.stringify({ key: "fullUrls", value: e.target.checked }));

  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
    if (e.key === "Escape") { tm && tm.call("close", ""); return; }
    if (!R) return;
    const big = e.shiftKey ? 5000 : 1000;
    if (e.key === " ") { e.preventDefault(); $("#p-play").click(); }
    else if (e.key === "ArrowLeft") { stopRewind(); seek(playhead - big, true); }
    else if (e.key === "ArrowRight") { stopRewind(); seek(playhead + big, true); }
    else if (e.key === "Home") rewind(false);
    else if (e.key === "End") $("#p-end").click();
    else if (e.key === "r" || e.key === "R") rewind(true);
  });

  /* ---------------------------------------------------------- connect */
  setSpeed(1);
  boot();
  requestAnimationFrame(frame);
  let lastTape = null;
  new QWebChannel(qt.webChannelTransport, (channel) => {
    tm = channel.objects.tm;
    tm.push.connect((topic, json) => {
      const d = JSON.parse(json);
      if (topic === "full") {
        const isNew = lastTape !== d.meta.id;
        lastTape = d.meta.id;
        loadFull(d, isNew);
      } else if (topic === "append") append(d);
      else if (topic === "empty") { lastTape = null; showEmpty(d); }
      else if (topic === "settings") setSettings(d);
      else if (topic === "opened") lastTape = null;      // every visit starts with a rewind
    });
    tm.ready();
  });
})();
