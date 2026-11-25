/* PRISM panel. Talks to Python (panel.py → PanelBridge) over QWebChannel:
   prism.call(action, json) to act, prism.push(topic, json) to receive data. */
(function () {
  "use strict";

  /* ============================================================ helpers */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString();
  const mb = (b) => b == null ? "-" : b >= 1073741824 ? (b / 1073741824).toFixed(2) + " GB" : (b / 1048576).toFixed(b < 10485760 ? 1 : 0) + " MB";
  const kb = (b) => b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(1) + " KB" : (b / 1048576).toFixed(2) + " MB";
  const view = (sec) => $(`section[data-view="${sec}"]`);
  const host = (u) => { try { return new URL(u).host; } catch (e) { return ""; } };
  const pathOf = (u) => { try { const x = new URL(u); return x.pathname + x.search; } catch (e) { return u; } };

  let prism = null;
  let section = "site";
  const D = {};                      // last data per topic
  let INIT = { permissionTypes: {}, dnsProviders: {}, securityHeaders: {} };
  const TITLES = {
    site: "Site report", network: "Network", source: "Source explorer", design: "Design review", api: "API tester", terminal: "Terminal",
    downloads: "Downloads", memory: "Tab memory", containers: "Containers", permissions: "Permissions", vault: "Password vault", bookmarks: "Dev bookmarks",
  };
  const call = (action, payload) => prism && prism.call(action, JSON.stringify(payload || {}));

  function toast(text) {
    const t = $("#toast");
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => t.classList.remove("show"), 3200);
  }
  function setHead(sub, actions) {
    $("#sec-title").textContent = TITLES[section];
    $("#sec-sub").textContent = sub || "";
    $("#head-actions").innerHTML = actions || "";
  }
  function copy(text, label) { call("copy", { text, label }); }

  const tip = $("#tip");
  function showTip(html, e) {
    tip.innerHTML = html;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(innerWidth - r.width - 8, e.clientX + 12) + "px";
    tip.style.top = Math.min(innerHeight - r.height - 8, e.clientY + 12) + "px";
  }
  const hideTip = () => { tip.hidden = true; };

  /* ======================================================== navigation */
  function show(sec, notify = true) {
    if (!TITLES[sec]) return;
    section = sec;
    $$(".rail button").forEach((b) => b.classList.toggle("on", b.dataset.sec === sec));
    $$("section[data-view]").forEach((s) => s.classList.toggle("on", s.dataset.view === sec));
    $("#body").scrollTop = 0;
    if (V[sec].init && !V[sec].ready) { V[sec].init(); V[sec].ready = true; }
    V[sec].head();
    if (D[sec]) V[sec].update(D[sec]);
    if (notify && prism) prism.setSection(sec);
  }
  $("#rail").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-sec]");
    if (b) show(b.dataset.sec);
  });

  /* Delegated actions: <button data-act="name" data-...> */
  const ACT = {};
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-act]");
    if (el && ACT[el.dataset.act]) { e.preventDefault(); ACT[el.dataset.act](el, e); }
  });
  document.addEventListener("change", (e) => {
    const el = e.target.closest("[data-change]");
    if (el && ACT[el.dataset.change]) ACT[el.dataset.change](el, e);
  });

  const V = {};

  /* =============================================================== SITE */
  let siteTab = "overview";
  V.site = {
    head() { setHead(D.site && !D.site.empty ? D.site.host : "", `<button class="btn sm" data-act="siteRecheck">Recheck</button>`); },
    update(d) {
      const el = view("site");
      if (d.empty || d.error) {
        el.innerHTML = d.error ? `<div class="empty"><b>Couldn't read this page</b>${esc(d.error)}</div>`
          : `<div class="empty"><b>No website in this tab</b>Open a site to see its trust score, cookies, trackers and scripts.</div>`;
        return;
      }
      setHead(d.host, `<button class="btn sm" data-act="siteRecheck">Recheck</button>`);
      const c = d.container;
      const tabs = [["overview", "Trust"], ["map", "Tracker map", d.map.nodes.length], ["cookies", "Cookies", d.cookies.length],
                    ["scripts", "Scripts", d.scripts.length], ["perms", "Permissions"]];
      let h = `<div class="site-id"><span class="host">${esc(d.host)}</span>
        ${c.id !== "default" ? `<span class="ctag" style="--cc:${esc(c.color)}">${esc(c.name)}</span>` : ""}
        <span class="grow"></span>
        <label class="tg" title="Ad / tracker blocking for this site"><span class="muted">shield</span>
          <span class="sw"><input type="checkbox" data-change="siteShield" ${d.shieldOn ? "checked" : ""}><i></i></span></label></div>`;
      h += `<div class="subtabs">${tabs.map(([k, l, n]) =>
        `<button data-act="siteTab" data-k="${k}" class="${siteTab === k ? "on" : ""}">${l}${n != null ? `<span class="count">${n}</span>` : ""}</button>`).join("")}</div>`;
      h += ({ overview: siteOverview, map: siteMap, cookies: siteCookies, scripts: siteScripts, perms: sitePerms })[siteTab](d);
      el.innerHTML = h;
      if (siteTab === "map") drawMap(d.map);
    },
  };
  ACT.siteTab = (b) => { siteTab = b.dataset.k; V.site.update(D.site); };
  ACT.siteRecheck = () => { call("site.refresh"); toast("Rechecking headers and score…"); };
  ACT.siteShield = () => call("site.shield");

  function gradeColor(g) { return g === "A" || g === "B" ? "var(--green)" : g === "C" ? "var(--warn)" : "var(--danger)"; }

  function siteOverview(d) {
    const t = d.trust;
    if (!t) return `<div class="empty">No score for this kind of page.</div>`;
    const r = 40, C = 2 * Math.PI * r, col = gradeColor(t.grade);
    let h = `<div class="trust-card"><div class="score">
      <svg viewBox="0 0 96 96"><circle class="track" cx="48" cy="48" r="${r}" fill="none"/>
      <circle class="val" cx="48" cy="48" r="${r}" fill="none" stroke="${col}" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - t.score / 100)}"/></svg>
      <div class="num"><div><b style="color:${col}">${t.score}</b><br><span>GRADE ${t.grade}</span></div></div></div>
      <ul class="checks">${t.checks.map((c) => {
        const ic = { pass: ["✓", "ok"], warn: ["▲", "warn"], fail: ["✕", "bad"], info: ["•", "muted"] }[c.state] || ["•", "muted"];
        return `<li><span class="ic ${ic[1]}">${ic[0]}</span><span>${esc(c.label)}</span><span class="delta">${c.delta ? c.delta : ""}</span>
          ${c.detail ? `<span class="d">${esc(c.detail)}</span>` : ""}</li>`;
      }).join("")}</ul></div>`;
    h += `<p class="note">The score starts at 100 and loses points for each risk PRISM can observe: encryption, known trackers,
      third-party reach, cookies, certificate and security headers. ${d.headersChecked ? "" : "Security headers are still being checked."}
      Headers are read with a separate request that carries no cookies.</p>`;
    h += `<h2>Blocked on this page <small>${fmt(d.blocked)} request(s)</small></h2>`;
    if (d.vault.entries && d.vault.entries.length) {
      h += `<h2>Saved logins</h2>` + d.vault.entries.map((e) =>
        `<div class="row" style="padding:3px 0"><span class="grow">${esc(e.username || "(no username)")}</span>
          <button class="btn sm" data-act="vaultFill" data-id="${e.id}">Fill</button></div>`).join("");
    } else if (d.vault.exists && !d.vault.unlocked) {
      h += `<p class="note">Your vault is locked. <a href="#" data-act="goto" data-sec="vault" class="ok">Unlock it</a> to fill saved logins here.</p>`;
    }
    return h;
  }

  function siteMap(d) {
    if (!d.map.nodes.length) {
      return `<div class="empty"><b>No third-party connections</b>This page only talks to ${esc(d.site)}.</div>`;
    }
    const trackers = d.map.nodes.filter((n) => n.tracker).length;
    return `<p class="note">Every outside company this page contacted. Circle size = number of requests.
      ${trackers ? `<b class="warn">${trackers}</b> are known ad / tracking domains.` : "None are known trackers."}</p>
      <div class="map-wrap"><svg class="map" id="map"></svg></div>
      <div class="legend"><span><i style="background:var(--danger)"></i>Tracker, blocked</span>
        <span><i style="background:var(--warn)"></i>Tracker, got through</span>
        <span><i style="background:#4fd8e8"></i>Other third party (CDN, fonts, APIs)</span></div>
      <h2>All third parties</h2>
      <table class="tbl"><tr><th>Domain</th><th class="num">Requests</th><th class="num">Blocked</th></tr>
      ${d.map.nodes.map((n) => `<tr><td>${esc(n.site)} ${n.tracker ? '<span class="badge warn">tracker</span>' : ""}
        <div class="muted" style="font-size:10.5px">${esc(n.hosts.slice(0, 4).join(", "))}${n.hosts.length > 4 ? "…" : ""}</div></td>
        <td class="num">${n.requests}</td><td class="num ${n.blocked ? "bad" : ""}">${n.blocked}</td></tr>`).join("")}</table>`;
  }

  function drawMap(map) {
    const svg = $("#map");
    if (!svg) return;
    const W = Math.max(300, svg.clientWidth || 360), N = Math.min(map.nodes.length, 22);
    const H = Math.max(260, Math.min(420, W * 0.86));
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.height = H + "px";
    const cx = W / 2, cy = H / 2, R = Math.max(70, Math.min(W / 2 - 112, H / 2 - 36));
    const nodes = map.nodes.slice(0, N);
    const max = Math.max(...nodes.map((n) => n.requests));
    let edges = "", dots = "";
    nodes.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / N) * Math.PI * 2;
      const x = cx + Math.cos(a) * R, y = cy + Math.sin(a) * R;
      const allBlocked = n.blocked && n.blocked === n.requests;
      const col = n.tracker ? (allBlocked ? "var(--danger)" : "var(--warn)") : "#4fd8e8";
      const rad = 4 + Math.sqrt(n.requests / max) * 11;
      edges += `<line class="edge" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${col}" stroke-opacity=".45" ${allBlocked ? 'stroke-dasharray="3 4"' : ""}/>`;
      const right = Math.cos(a) >= 0;
      const lx = x + Math.cos(a) * (rad + 6), ly = y + Math.sin(a) * (rad + 6) + 3;
      const label = n.site.length > 22 ? n.site.slice(0, 21) + "…" : n.site;
      dots += `<g class="node" data-i="${i}"><circle cx="${x}" cy="${y}" r="${rad}" fill="${col}" fill-opacity=".22" stroke="${col}"/>
        <text x="${lx}" y="${ly}" text-anchor="${Math.abs(Math.cos(a)) < 0.2 ? "middle" : right ? "start" : "end"}">${esc(label)}</text>
        <circle cx="${x}" cy="${y}" r="${rad + 8}" fill="transparent"/></g>`;
    });
    const more = map.nodes.length - N;
    svg.innerHTML = edges + dots +
      `<circle cx="${cx}" cy="${cy}" r="18" fill="#04140b" stroke="var(--green)" stroke-width="2"/>
       <text x="${cx}" y="${cy + 34}" text-anchor="middle" fill="var(--text)" font-size="11" font-family="var(--mono)">${esc(map.site)}</text>
       ${more > 0 ? `<text x="${W - 6}" y="${H - 6}" text-anchor="end" fill="var(--muted)" font-size="10">+${more} more in the table</text>` : ""}`;
    svg.onmousemove = (e) => {
      const g = e.target.closest(".node");
      if (!g) return hideTip();
      const n = nodes[+g.dataset.i];
      const types = Object.entries(n.types).map(([k, v]) => `${k} ${v}`).join(" · ");
      showTip(`<b>${esc(n.site)}</b>${n.tracker ? " · known tracker" : ""}<br>${n.requests} requests, ${n.blocked} blocked<br>
        <span class="muted">${esc(types)}</span><br>${n.hosts.slice(0, 6).map(esc).join("<br>")}`, e);
    };
    svg.onmouseleave = hideTip;
  }

  function siteCookies(d) {
    const by = {};
    d.cookies.forEach((c) => { by[c.purpose] = (by[c.purpose] || 0) + 1; });
    const colors = { session: "#7fe3ff", security: "var(--green)", analytics: "var(--warn)", advertising: "var(--danger)",
                     consent: "var(--text-2)", preference: "var(--text-2)", support: "var(--text-2)", unknown: "var(--muted)" };
    let h = "";
    if (!d.cookies.length) {
      h += `<div class="empty"><b>No cookies from ${esc(d.site)}</b>This site hasn't stored any cookies in this container.</div>`;
    } else {
      h += `<div class="bar-stack">${Object.entries(by).map(([p, n]) => `<i style="flex:${n};background:${colors[p]}" title="${p}: ${n}"></i>`).join("")}</div>
        <div class="legend">${Object.entries(by).map(([p, n]) => `<span><i style="background:${colors[p]}"></i>${p} ${n}</span>`).join("")}</div>
        <h2>${d.cookies.length} cookie(s) <span class="grow"></span><button class="btn sm danger" data-act="cookiesClear">Delete all</button></h2>
        <table class="tbl"><tr><th>Name</th><th>Purpose</th><th>Expires</th><th></th></tr>
        ${d.cookies.map((c) => `<tr><td><span class="mono">${esc(c.name)}</span>
            <div style="margin-top:2px"><span class="flag">${esc(c.domain)}${esc(c.path !== "/" ? c.path : "")}</span>
            <span class="flag ${c.secure ? "on" : ""}">${c.secure ? "Secure" : "not Secure"}</span>
            <span class="flag ${c.httpOnly ? "on" : ""}">${c.httpOnly ? "HttpOnly" : "JS-readable"}</span>
            ${c.sameSite ? `<span class="flag on">SameSite=${esc(c.sameSite)}</span>` : ""}<span class="flag">${kb(c.size)}</span></div></td>
          <td><span class="purpose p-${c.purpose}">${c.purpose}</span><div class="muted" style="font-size:10.5px">${esc(c.who)}</div></td>
          <td class="muted" style="white-space:nowrap">${c.session ? "end of session" : esc(c.expires.replace("T", " ").slice(0, 16))}</td>
          <td><button class="x" data-act="cookieDel" data-key="${esc(c.key)}" title="Delete">✕</button></td></tr>`).join("")}</table>
        <p class="note">Purposes are matched from well-known cookie names, so "unknown" just means PRISM can't tell.
          Nothing is ever kept after you close PRISM or purge.</p>`;
    }
    h += `<h2>Third-party cookies refused <small>${d.refused.reduce((a, r) => a + r.count, 0)}</small></h2>`;
    h += d.refused.length ? `<table class="tbl">${d.refused.map((r) => `<tr><td class="mono">${esc(r.origin)}</td><td class="num">${r.count}×</td></tr>`).join("")}</table>`
      : `<p class="note">No other site tried to set a cookie here.</p>`;
    return h;
  }
  ACT.cookieDel = (b) => call("site.cookieDelete", { key: b.dataset.key });
  ACT.cookiesClear = () => call("site.cookiesClear");

  function siteScripts(d) {
    const r = d.rule;
    let h = `<div class="box">
      <label class="tg"><span class="sw"><input type="checkbox" data-change="siteJs" ${d.sandbox ? (d.sandboxJs ? "checked" : "") : (r.js ? "checked" : "")}><i></i></span>
        <span class="grow"><b>JavaScript</b> on ${esc(d.site)}<div class="muted" style="font-size:11px">${d.sandbox ? "Sandbox tab: scripts are off until you allow them." : "Turn off to read pages without any scripts running."}</div></span></label>
      <label class="tg"><span class="sw"><input type="checkbox" data-change="siteThird" ${r.thirdParty === "block" ? "checked" : ""}><i></i></span>
        <span class="grow"><b>Block all third-party scripts</b><div class="muted" style="font-size:11px">Only ${esc(d.site)}'s own code runs. Some sites break.</div></span></label></div>`;
    if (!d.scripts.length) return h + `<div class="empty"><b>No scripts loaded</b>${r.js ? "This page didn't load any script files." : "JavaScript is off for this site."}</div>`;
    h += `<h2>Script sources <small>toggle to block one host</small></h2><table class="tbl">
      <tr><th>Host</th><th class="num">Files</th><th>Status</th><th>Allow</th></tr>`;
    h += d.scripts.map((s) => {
      const ruleBlocked = r.blockedHosts.includes(s.host);
      const status = s.blocked ? `<span class="badge bad">${esc(s.blocked)}</span>` : `<span class="badge ok">ran</span>`;
      return `<tr><td><span class="mono">${esc(s.host)}</span> ${s.third ? '<span class="badge">3rd party</span>' : '<span class="badge ok">1st party</span>'}
          <div class="muted" style="font-size:10.5px;word-break:break-all">${s.urls.slice(0, 2).map((u) => esc(pathOf(u))).join("<br>")}</div></td>
        <td class="num">${s.count}</td><td>${status}</td>
        <td><span class="sw"><input type="checkbox" data-change="scriptHost" data-host="${esc(s.host)}" ${ruleBlocked ? "" : "checked"}><i></i></span></td></tr>`;
    }).join("") + `</table><p class="note">Changes reload the page. Rules are saved per site.</p>`;
    return h;
  }
  ACT.siteJs = (i) => call("site.js", { on: i.checked });
  ACT.siteThird = (i) => call("site.thirdParty", { block: i.checked });
  ACT.scriptHost = (i) => call("site.blockHost", { host: i.dataset.host, block: !i.checked });

  function sitePerms(d) {
    return `<p class="note">What ${esc(d.site)} may use. "Default" follows the Permission center.</p>
      <table class="tbl">${d.permissions.map((p) => `<tr><td>${esc(p.label)}</td><td style="text-align:right">
        <div class="seg">${[["", "Default"], ["allow", "Allow"], ["block", "Block"]].map(([v, l]) =>
          `<button data-act="sitePerm" data-type="${p.type}" data-v="${v}" class="${(p.custom ? p.policy : "") === v ? "on" : ""} ${v === "block" ? "b" : ""}">${l}${v === "" ? ` <span class="muted">(${p.custom ? "…" : p.policy})</span>` : ""}</button>`).join("")}
        </div></td></tr>`).join("")}</table>`;
  }
  ACT.sitePerm = (b) => call("site.permission", { type: b.dataset.type, policy: b.dataset.v || null });
  ACT.vaultFill = (b) => call("vault.fill", { id: b.dataset.id });
  ACT.goto = (a) => show(a.dataset.sec);

  /* ============================================================ NETWORK */
  const NF = { q: "", type: "all", blocked: false, third: false, sel: -1 };
  const TYPES = ["all", "document", "script", "xhr", "stylesheet", "image", "font", "media", "subframe", "other"];
  V.network = {
    init() {
      view("network").innerHTML = `
        <div class="summary-line" id="net-sum"></div>
        <div class="netfilters">
          <input type="search" id="net-q" placeholder="filter by URL or host">
          <label class="tg"><span class="sw"><input type="checkbox" id="net-blk"><i></i></span>blocked</label>
          <label class="tg"><span class="sw"><input type="checkbox" id="net-3p"><i></i></span>3rd party</label>
        </div>
        <div class="chips" id="net-types" style="margin-bottom:8px">${TYPES.map((t) => `<button class="chip ${t === "all" ? "on" : ""}" data-t="${t}">${t}</button>`).join("")}</div>
        <div class="log" id="net-log"></div>
        <div class="detail" id="net-detail"></div>

        <h2>Protection</h2>
        <div class="box">
          <label class="tg"><span class="sw"><input type="checkbox" data-change="netProt" data-key="malware" id="np-malware"><i></i></span>
            <span class="grow"><b>Malware &amp; phishing domains</b><div class="muted" style="font-size:11px" id="np-malware-sub"></div></span></label>
          <label class="tg"><span class="sw"><input type="checkbox" data-change="netProt" data-key="suspiciousScripts" id="np-susp"><i></i></span>
            <span class="grow"><b>Suspicious scripts</b><div class="muted" style="font-size:11px">Blocks third-party code served from bare IP addresses, a common malware pattern.</div></span></label>
        </div>
        <h2>Your block list <small>hosts PRISM never contacts</small></h2>
        <div class="row"><input type="text" id="cb-host" class="grow" placeholder="e.g. telemetry.example.com"><button class="btn" data-act="cbAdd">Block</button></div>
        <div id="cb-list" style="margin-top:6px"></div>
        <div id="mal-allow"></div>

        <h2>Search <small>SearXNG</small></h2>
        <div class="box stack" id="search-box"></div>

        <h2>Encrypted DNS <small>DNS-over-HTTPS</small></h2>
        <div class="box stack" id="dns-box"></div>`;
      $("#net-q").addEventListener("input", (e) => { NF.q = e.target.value.toLowerCase(); NF.sel = -1; drawLog(); });
      $("#net-blk").addEventListener("change", (e) => { NF.blocked = e.target.checked; drawLog(); });
      $("#net-3p").addEventListener("change", (e) => { NF.third = e.target.checked; drawLog(); });
      $("#net-types").addEventListener("click", (e) => {
        const b = e.target.closest("[data-t]");
        if (!b) return;
        NF.type = b.dataset.t;
        $$("#net-types .chip").forEach((c) => c.classList.toggle("on", c === b));
        drawLog();
      });
      $("#cb-host").addEventListener("keydown", (e) => { if (e.key === "Enter") ACT.cbAdd(); });
    },
    head() { setHead(D.network ? host(D.network.page) : "", `<button class="btn sm" data-act="netExport">Copy as JSON</button>`); },
    update(d) {
      const r = d.reasons, blockedN = Object.values(r).reduce((a, b) => a + b, 0);
      $("#net-sum").innerHTML = `<span><b>${fmt(d.total)}</b> requests</span><span><b class="bad">${fmt(blockedN)}</b> blocked</span>` +
        Object.entries(r).map(([k, v]) => `<span>${esc(k)} ${v}</span>`).join("") +
        (d.dropped ? `<span class="warn">${d.dropped} not logged (page too busy)</span>` : "");
      drawLog();
      $("#np-malware").checked = !!d.protection.malware;
      $("#np-susp").checked = !!d.protection.suspiciousScripts;
      $("#np-malware-sub").textContent = `${fmt(d.lists.malware)} known bad domains from ${d.lists.securitySources.join(", ") || "no lists (run update_blocklists.py)"}. Pages show a warning instead.`;
      $("#cb-list").innerHTML = d.custom.length ? d.custom.map((h) =>
        `<div class="row" style="padding:3px 0"><span class="mono grow">${esc(h)}</span><button class="x" data-act="cbDel" data-host="${esc(h)}">✕</button></div>`).join("")
        : `<p class="note">Nothing yet. Add a domain, or block a host from the request log above.</p>`;
      $("#mal-allow").innerHTML = d.allowedMalware.length ? `<p class="note warn">Allowed despite a warning this session: ${d.allowedMalware.map(esc).join(", ")}</p>` : "";
      drawDns(d);
      drawSearch(d.search);
    },
  };

  function drawSearch(s) {
    const box = $("#search-box");
    if (!box || box.contains(document.activeElement)) return;
    box.innerHTML = `
      <p class="note" style="margin-top:0">PRISM searches with <b>SearXNG</b>: open-source metasearch that asks several engines
        for you and returns the results without ads, tracking or a profile. Public instances are shared and sometimes busy;
        PRISM then moves on to the next one. Your own instance is the most private and never busy.</p>
      <div class="kv" style="grid-template-columns:max-content 1fr"><dt>searching on</dt><dd class="mono">${esc(s.current)}</dd>
        ${s.busy.length ? `<dt>busy</dt><dd class="warn mono">${s.busy.map(esc).join(", ")}</dd>` : ""}</div>
      <div class="row"><input type="text" id="sx-inst" class="grow" placeholder="your instance, e.g. https://search.example.org"
        value="${esc(s.instance)}"><button class="btn sm" data-act="sxSave">Use</button>${s.instance ? `<button class="btn sm" data-act="sxClear">Clear</button>` : ""}</div>
      <label class="tg"><span class="sw"><input type="checkbox" data-change="sxPublic" ${s.publicFallback ? "checked" : ""}><i></i></span>
        <span class="grow">Use public instances when mine is unreachable</span></label>
      <div class="muted" style="font-size:11px">Public: ${s.public.map(esc).join(" · ")}</div>`;
    $("#sx-inst").addEventListener("keydown", (e) => { if (e.key === "Enter") ACT.sxSave(); });
  }
  ACT.sxSave = () => call("net.search", { instance: $("#sx-inst").value, publicFallback: D.network.search.publicFallback });
  ACT.sxClear = () => call("net.search", { instance: "", publicFallback: true });
  ACT.sxPublic = (i) => call("net.search", { instance: D.network.search.instance, publicFallback: i.checked });
  function logRows() {
    const d = D.network;
    if (!d) return [];
    return d.entries.map((e, i) => ({ ...e, i })).filter((e) =>
      (NF.type === "all" || e.type === NF.type || (NF.type === "other" && !TYPES.includes(e.type))) &&
      (!NF.blocked || e.blocked) && (!NF.third || e.third) &&
      (!NF.q || e.url.toLowerCase().includes(NF.q)));
  }
  function drawLog() {
    const rows = logRows();
    const box = $("#net-log");
    if (!box) return;
    if (!rows.length) {
      box.innerHTML = `<div class="empty" style="padding:14px">${D.network && D.network.total ? "No requests match the filter." : "<b>No requests yet</b>Load a page and every request it makes shows up here."}</div>`;
    } else {
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
      box.innerHTML = `<table class="tbl"><colgroup><col style="width:42px"><col style="width:62px"><col style="width:34%"><col><col style="width:62px"></colgroup>
        <tr><th class="num">ms</th><th>type</th><th>host</th><th>path</th><th></th></tr>${rows.slice(-500).map((e) =>
        `<tr class="click ${e.blocked ? "blocked" : ""} ${e.i === NF.sel ? "sel" : ""}" data-act="netSel" data-i="${e.i}">
          <td class="num muted">${e.t}</td><td class="muted">${esc(e.type)}</td><td>${esc(e.host)}${e.third ? "" : ' <span class="ok">•</span>'}</td>
          <td title="${esc(e.url)}">${esc(pathOf(e.url))}</td><td>${e.blocked ? `<span class="badge bad">${esc(e.blocked)}</span>` : ""}</td></tr>`).join("")}</table>`;
      if (atBottom) box.scrollTop = box.scrollHeight;
    }
    const sel = D.network && D.network.entries[NF.sel];
    $("#net-detail").innerHTML = sel ? `<div class="box"><div class="url">${esc(sel.url)}</div>
      <div class="row wrap" style="margin-top:8px">
        <span class="badge">${esc(sel.type)}</span>${sel.third ? '<span class="badge warn">third party</span>' : '<span class="badge ok">first party</span>'}
        ${sel.blocked ? `<span class="badge bad">blocked: ${esc(sel.blocked)}</span>` : ""}<span class="grow"></span>
        <button class="btn sm" data-act="copyText" data-text="${esc(sel.url)}">Copy URL</button>
        <button class="btn sm" data-act="openUrl" data-url="${esc(sel.url)}">Open</button>
        <button class="btn sm danger" data-act="cbAddHost" data-host="${esc(sel.host)}">Always block ${esc(sel.host)}</button></div></div>` : "";
  }
  ACT.netSel = (tr) => { NF.sel = +tr.dataset.i; drawLog(); };
  ACT.netProt = (i) => call("net.protection", { key: i.dataset.key, on: i.checked });
  ACT.cbAdd = () => { const i = $("#cb-host"); if (i.value.trim()) { call("net.customAdd", { host: i.value }); i.value = ""; } };
  ACT.cbAddHost = (b) => call("net.customAdd", { host: b.dataset.host });
  ACT.cbDel = (b) => call("net.customRemove", { host: b.dataset.host });
  ACT.copyText = (b) => copy(b.dataset.text);
  ACT.openUrl = (b) => call("tab.open", { url: b.dataset.url });
  ACT.netExport = () => D.network && copy(JSON.stringify(D.network.entries, null, 2), `Copied ${D.network.entries.length} requests`);

  function drawDns(d) {
    const box = $("#dns-box");
    if (box.contains(document.activeElement)) return;
    const s = d.dns, run = d.dnsRunning;
    const pending = (run ? (run.strict ? "strict" : "secure") : "off") !== s.mode ||
      (run && INIT.dnsProviders[s.provider] && !run.template.includes(s.provider === "google" ? "dns.google" : s.provider));
    box.innerHTML = `
      <div class="seg">${[["off", "Off"], ["secure", "On, with fallback"], ["strict", "Strict"]].map(([v, l]) =>
        `<button data-act="dnsMode" data-v="${v}" class="${s.mode === v ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="row"><span class="muted">Provider</span><select data-change="dnsProv" class="grow">${Object.entries(INIT.dnsProviders).map(([k, l]) =>
        `<option value="${k}" ${s.provider === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
      <p class="note">Your ISP and network can read normal DNS lookups and see every site you visit. With this on, PRISM
        resolves hostnames over HTTPS through a local proxy. <b>Strict</b> never falls back to plain DNS, so sites fail to load
        if the provider is unreachable.</p>
      ${pending ? `<p class="warn">Restart PRISM to apply the new setting.</p>` : ""}
      ${run ? `<div class="kv" style="grid-template-columns:max-content 1fr"><dt>status</dt><dd class="ok">active${run.strict ? " (strict)" : ""}</dd>
        <dt>lookups</dt><dd>${fmt(run.queries)} encrypted · ${fmt(run.cached)} cached · ${fmt(run.fallbacks)} fell back · ${fmt(run.failures)} failed</dd>
        ${run.lastError ? `<dt>last error</dt><dd class="warn">${esc(run.lastError)}</dd>` : ""}</div>` : `<div class="muted">Not active.</div>`}
      <div class="row"><input type="text" id="dns-test" value="example.com" class="grow"><button class="btn sm" data-act="dnsTest">Test lookup</button></div>
      <div id="dns-test-out" class="muted"></div>`;
  }
  ACT.dnsMode = (b) => call("net.dns", { mode: b.dataset.v, provider: D.network.dns.provider });
  ACT.dnsProv = (s) => call("net.dns", { mode: D.network.dns.mode, provider: s.value });
  ACT.dnsTest = () => { $("#dns-test-out").textContent = "Looking up…"; call("net.test", { host: $("#dns-test").value }); };

  /* ============================================================= SOURCE */
  let srcTab = "html", srcFind = "", srcHit = 0;
  V.source = {
    init() {
      view("source").innerHTML = `<div class="subtabs" id="src-tabs">${[["html", "Source"], ["meta", "Metadata"], ["headers", "Headers"], ["res", "Resources"]].map(([k, l]) =>
        `<button data-act="srcTab" data-k="${k}" class="${k === srcTab ? "on" : ""}">${l}</button>`).join("")}</div><div id="src-body"><div class="loading">loading source</div></div>`;
    },
    head() { setHead(D.sourceHtml ? host(D.sourceHtml.url) : "", `<button class="btn sm" data-act="srcLoad">Reload</button>`); },
    update() { drawSource(); },
    load() { $("#src-body") && ($("#src-body").innerHTML = `<div class="loading">loading source</div>`); call("source.load"); },
  };
  ACT.srcTab = (b) => { srcTab = b.dataset.k; $$("#src-tabs button").forEach((x) => x.classList.toggle("on", x === b)); drawSource(); };
  ACT.srcLoad = () => V.source.load();

  function hlHtml(line) {
    return line.replace(/(&lt;!--.*?--&gt;)|(&lt;!DOCTYPE[^&]*&gt;)|(&lt;\/?)([a-zA-Z][\w:-]*)|([\w:@.-]+)(=)(&quot;.*?&quot;|&#39;.*?&#39;)/gi,
      (m, com, doc, lt, tag, attr, eq, str) => com ? `<span class="h-com">${com}</span>` : doc ? `<span class="h-doc">${doc}</span>`
        : tag ? `${lt}<span class="h-tag">${tag}</span>` : `<span class="h-attr">${attr}</span>${eq}<span class="h-str">${str}</span>`);
  }
  function drawSource() {
    const box = $("#src-body");
    if (!box) return;
    const d = D.source;
    if (d && d.empty) { box.innerHTML = `<div class="empty"><b>No website in this tab</b>Open a page to explore its source.</div>`; return; }
    if (srcTab === "html") {
      const s = D.sourceHtml;
      if (!s) { box.innerHTML = `<div class="loading">loading source</div>`; return; }
      const lines = s.html.split("\n");
      const LIMIT = 6000;
      const q = srcFind.toLowerCase();
      const hits = [];
      const body = lines.slice(0, LIMIT).map((ln, i) => {
        let h = esc(ln);
        if (q && ln.toLowerCase().includes(q)) {
          hits.push(i);
          const re = new RegExp(esc(srcFind).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
          h = h.replace(re, (m) => `<mark class="hit">${m}</mark>`);
        } else {
          h = hlHtml(h);
        }
        return `<div class="ln" data-l="${i}"><span>${h || " "}</span></div>`;
      }).join("");
      box.innerHTML = `<div class="row" style="margin-bottom:8px"><input type="search" id="src-find" class="grow" placeholder="find in source" value="${esc(srcFind)}">
          <span class="muted" id="src-hits">${q ? `${hits.length ? srcHit + 1 : 0}/${hits.length} lines` : `${fmt(lines.length)} lines · ${kb(s.html.length)}`}</span>
          <button class="btn sm" data-act="copySource">Copy</button></div>
        <div class="code" id="src-code">${body}</div>
        ${lines.length > LIMIT ? `<p class="note">Showing the first ${fmt(LIMIT)} of ${fmt(lines.length)} lines. Copy for the rest.</p>` : ""}
        ${s.truncated ? `<p class="note warn">Very large page: source cut at 3 MB.</p>` : ""}`;
      const f = $("#src-find");
      f.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          if (f.value !== srcFind) { srcFind = f.value; srcHit = 0; } else { srcHit = hits.length ? (srcHit + (e.shiftKey ? -1 + hits.length : 1)) % hits.length : 0; }
          drawSource();
          setTimeout(() => { const nf = $("#src-find"); nf.focus(); nf.setSelectionRange(nf.value.length, nf.value.length); }, 0);
        }
      });
      if (q && hits.length) {
        const ln = $(`#src-code .ln[data-l="${hits[Math.min(srcHit, hits.length - 1)]}"]`);
        if (ln) { ln.querySelectorAll(".hit").forEach((m) => m.classList.add("cur")); ln.scrollIntoView({ block: "center" }); }
      }
    } else if (srcTab === "meta") {
      const m = D.sourceMeta;
      if (!m) { box.innerHTML = `<div class="loading">reading metadata</div>`; return; }
      if (!m.title && m.size === undefined) { box.innerHTML = `<div class="empty">Couldn't read this page's DOM.</div>`; return; }
      const c = m.counts || {};
      box.innerHTML = `<dl class="kv"><dt>title</dt><dd>${esc(m.title)}</dd><dt>language</dt><dd>${esc(m.lang || "(not set)")}</dd>
          <dt>charset</dt><dd>${esc(m.charset)}</dd><dt>doctype</dt><dd>${esc(m.doctype)} · ${esc(m.mode)}</dd>
          <dt>DOM</dt><dd>${fmt(c.elements)} elements · ${kb(m.size || 0)} HTML</dd>
          <dt>assets</dt><dd>${c.scripts} scripts (${c.inlineScripts} inline) · ${c.styles} styles · ${c.images} images · ${c.iframes} iframes · ${c.links} links</dd>
          <dt>modified</dt><dd>${esc(m.lastModified)}</dd></dl>
        <h2>Meta tags <small>${m.meta.length}</small></h2>
        ${m.meta.length ? `<table class="tbl">${m.meta.map((x) => `<tr><td class="mono" style="white-space:nowrap">${esc(x.name)}</td><td>${esc(x.content)}</td></tr>`).join("")}</table>` : `<p class="note">None.</p>`}
        <h2>Linked resources <small>${m.links.length}</small></h2>
        ${m.links.length ? `<table class="tbl">${m.links.map((x) => `<tr><td class="mono">${esc(x.rel)}</td><td class="ell" style="max-width:240px"><a href="#" data-act="openUrl" data-url="${esc(x.href)}" class="ok">${esc(x.href)}</a></td></tr>`).join("")}</table>` : `<p class="note">None.</p>`}
        <h2>Forms <small>${m.forms.length}</small></h2>
        ${m.forms.length ? `<table class="tbl">${m.forms.map((f) => `<tr><td>${esc(f.method)}</td><td class="mono" style="word-break:break-all">${esc(f.action)}</td>
          <td>${f.password ? (f.action.startsWith("https:") ? '<span class="badge warn">password</span>' : '<span class="badge bad">password over http</span>') : ""}</td></tr>`).join("")}</table>` : `<p class="note">No forms on this page.</p>`}
        ${m.iframes.length ? `<h2>Iframes</h2>${m.iframes.map((s) => `<div class="mono muted" style="word-break:break-all">${esc(s)}</div>`).join("")}` : ""}`;
    } else if (srcTab === "headers") {
      const hd = d && d.headers;
      if (!hd) { box.innerHTML = `<div class="loading">fetching headers</div>`; return; }
      if (!hd.ok) { box.innerHTML = `<div class="empty"><b>Couldn't fetch headers</b>${esc(hd.certError || hd.error || "")}</div>`; return; }
      const present = new Set(hd.headers.map(([k]) => k.toLowerCase()));
      box.innerHTML = `<dl class="kv"><dt>status</dt><dd>${hd.status}</dd><dt>final URL</dt><dd class="mono">${esc(hd.finalUrl)}</dd><dt>time</dt><dd>${hd.timeMs} ms</dd>
          ${hd.tls && !hd.tls.error ? `<dt>TLS</dt><dd>${esc(hd.tls.version)} · ${esc(hd.tls.cipher)}</dd><dt>certificate</dt><dd>${esc(hd.tls.issuer)} · expires ${esc(hd.tls.expires)}</dd>` : ""}</dl>
        <h2>Security headers</h2>
        <table class="tbl">${Object.entries(INIT.securityHeaders).map(([k, why]) => `<tr><td class="${present.has(k) ? "ok" : "warn"}">${present.has(k) ? "✓" : "▲"}</td>
          <td class="mono">${esc(k)}</td><td class="muted">${esc(why)}</td></tr>`).join("")}</table>
        <h2>Response headers <small>${hd.headers.length}</small> <span class="grow"></span><button class="btn sm" data-act="copyText" data-text="${esc(hd.headers.map(([k, v]) => k + ": " + v).join("\n"))}">Copy</button></h2>
        <table class="tbl">${hd.headers.map(([k, v]) => `<tr><td class="mono" style="white-space:nowrap">${esc(k)}</td><td style="word-break:break-all">${esc(v)}</td></tr>`).join("")}</table>
        <p class="note">Fetched separately by PRISM (no cookies), so they can differ slightly from what the page itself received.</p>`;
    } else {
      const res = (d && d.resources) || [];
      const by = {};
      res.forEach((e) => { by[e.type] = (by[e.type] || 0) + 1; });
      box.innerHTML = res.length ? `<div class="summary-line">${Object.entries(by).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<span><b>${v}</b> ${esc(k)}</span>`).join("")}</div>
        <table class="tbl"><tr><th>type</th><th>URL</th><th></th></tr>${res.map((e) => `<tr class="${e.blocked ? "blocked" : ""}"><td class="muted">${esc(e.type)}</td>
          <td class="mono" style="word-break:break-all;font-size:11px">${esc(e.url)}</td><td>${e.blocked ? `<span class="badge bad">${esc(e.blocked)}</span>` : ""}</td></tr>`).join("")}</table>`
        : `<div class="empty"><b>Nothing recorded</b>Reload the page to capture its resources.</div>`;
    }
  }
  ACT.copySource = () => D.sourceHtml && copy(D.sourceHtml.html, "Source copied");

  /* ================================================================ API */
  const REQ = { method: "GET", url: "", headers: [{ on: true, name: "Accept", value: "application/json" }], body: "", timeout: 30, follow: true };
  let apiTab = "params", resTab = "body", apiRes = null, apiBusy = false, reqId = 0;
  const hist = [];
  V.api = {
    init() {
      view("api").innerHTML = `
        <div class="reqline"><select id="api-m">${["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].map((m) => `<option>${m}</option>`).join("")}</select>
          <input type="text" id="api-url" placeholder="https://api.example.com/v1/items" spellcheck="false">
          <button class="btn primary" id="api-send" data-act="apiSend">Send</button></div>
        <div class="subtabs" id="api-tabs" style="margin-top:10px">${[["params", "Params"], ["headers", "Headers"], ["body", "Body"], ["opts", "Settings"]].map(([k, l]) =>
          `<button data-act="apiTab" data-k="${k}" class="${k === apiTab ? "on" : ""}">${l}<span class="count" id="api-c-${k}"></span></button>`).join("")}</div>
        <div id="api-edit"></div>
        <div id="api-res"></div>
        <h2>History <small>this session</small></h2><ul class="hist" id="api-hist"></ul>`;
      $("#api-m").addEventListener("change", (e) => { REQ.method = e.target.value; drawApiEdit(); });
      $("#api-url").addEventListener("input", (e) => { REQ.url = e.target.value; if (apiTab === "params") drawApiEdit(true); });
      $("#api-url").addEventListener("keydown", (e) => { if (e.key === "Enter") ACT.apiSend(); });
      drawApiEdit();
      drawHist();
    },
    head() { setHead("send requests without CORS limits", `<button class="btn sm" data-act="apiCurl">Copy as cURL</button><button class="btn sm" data-act="apiSave">Save</button>`); },
    update() {},
  };
  function parseParams(url) {
    const q = url.split("#")[0].split("?")[1];
    if (!q) return [];
    return q.split("&").filter(Boolean).map((p) => {
      const [k, ...v] = p.split("=");
      const dec = (s) => { try { return decodeURIComponent(s.replace(/\+/g, " ")); } catch (e) { return s; } };
      return { name: dec(k), value: dec(v.join("=")) };
    });
  }
  function setParams(rows) {
    const base = REQ.url.split("#")[0].split("?")[0];
    const q = rows.filter((r) => r.name).map((r) => encodeURIComponent(r.name) + "=" + encodeURIComponent(r.value)).join("&");
    REQ.url = base + (q ? "?" + q : "");
    $("#api-url").value = REQ.url;
  }
  function kvRows(rows, kind) {
    return `<div class="kvrows">${rows.map((r, i) => `<div class="kvr">
        ${kind === "headers" ? `<input type="checkbox" data-kv="${kind}" data-i="${i}" data-f="on" ${r.on !== false ? "checked" : ""}>` : "<span></span>"}
        <input type="text" placeholder="name" value="${esc(r.name)}" data-kv="${kind}" data-i="${i}" data-f="name">
        <input type="text" placeholder="value" value="${esc(r.value)}" data-kv="${kind}" data-i="${i}" data-f="value">
        <button class="x" data-act="kvDel" data-kind="${kind}" data-i="${i}">✕</button></div>`).join("")}
      <button class="btn sm" data-act="kvAdd" data-kind="${kind}">+ add</button></div>`;
  }
  function drawApiEdit(paramsOnly) {
    const box = $("#api-edit");
    if (paramsOnly && box.contains(document.activeElement)) return;
    $("#api-c-params").textContent = parseParams(REQ.url).length || "";
    $("#api-c-headers").textContent = REQ.headers.filter((h) => h.on !== false && h.name).length || "";
    $("#api-c-body").textContent = REQ.body ? "•" : "";
    if (apiTab === "params") {
      box.innerHTML = kvRows(parseParams(REQ.url), "params") + `<p class="note">Edits here rewrite the URL's query string.</p>`;
    } else if (apiTab === "headers") {
      box.innerHTML = kvRows(REQ.headers, "headers") + `<div class="chips" style="margin-top:8px">${["Authorization: Bearer ", "Content-Type: application/json", "Accept: text/html", "Cache-Control: no-cache"].map((h) =>
        `<button class="chip" data-act="hdrPreset" data-h="${esc(h)}">${esc(h.split(":")[0])}</button>`).join("")}</div>`;
    } else if (apiTab === "body") {
      const disabled = REQ.method === "GET" || REQ.method === "HEAD";
      box.innerHTML = `<textarea id="api-body" rows="9" spellcheck="false" placeholder='{"name": "value"}' ${disabled ? "disabled" : ""}>${esc(REQ.body)}</textarea>
        <div class="row" style="margin-top:6px"><button class="btn sm" data-act="apiFmt">Format JSON</button>
        <span class="muted grow">${disabled ? `${REQ.method} requests have no body.` : "JSON bodies get Content-Type: application/json automatically."}</span></div>`;
      const ta = $("#api-body");
      ta.addEventListener("input", () => { REQ.body = ta.value; $("#api-c-body").textContent = REQ.body ? "•" : ""; });
    } else {
      box.innerHTML = `<div class="stack"><label class="tg"><span class="muted" style="width:120px">Timeout (s)</span><input type="number" id="api-to" min="1" max="120" value="${REQ.timeout}" style="width:80px"></label>
        <label class="tg"><span class="sw"><input type="checkbox" id="api-follow" ${REQ.follow ? "checked" : ""}><i></i></span>Follow redirects</label>
        <p class="note">Requests are sent by PRISM itself, not the page, so there are no CORS limits and no browser cookies are attached.</p></div>`;
      $("#api-to").addEventListener("change", (e) => { REQ.timeout = +e.target.value || 30; });
      $("#api-follow").addEventListener("change", (e) => { REQ.follow = e.target.checked; });
    }
  }
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!el.dataset || !el.dataset.kv) return;
    const i = +el.dataset.i, f = el.dataset.f;
    if (el.dataset.kv === "headers") {
      REQ.headers[i][f] = f === "on" ? el.checked : el.value;
      $("#api-c-headers").textContent = REQ.headers.filter((h) => h.on !== false && h.name).length || "";
    } else {
      const rows = parseParams(REQ.url);
      rows[i][f] = el.value;
      setParams(rows);
    }
  });
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.dataset && el.dataset.kv === "headers" && el.dataset.f === "on") REQ.headers[+el.dataset.i].on = el.checked;
  });
  ACT.apiTab = (b) => { apiTab = b.dataset.k; $$("#api-tabs button").forEach((x) => x.classList.toggle("on", x === b)); drawApiEdit(); };
  ACT.kvAdd = (b) => {
    if (b.dataset.kind === "headers") REQ.headers.push({ on: true, name: "", value: "" });
    else { const r = parseParams(REQ.url); r.push({ name: "key", value: "" }); setParams(r); }
    drawApiEdit();
  };
  ACT.kvDel = (b) => {
    if (b.dataset.kind === "headers") REQ.headers.splice(+b.dataset.i, 1);
    else { const r = parseParams(REQ.url); r.splice(+b.dataset.i, 1); setParams(r); }
    drawApiEdit();
  };
  ACT.hdrPreset = (b) => {
    const [n, ...v] = b.dataset.h.split(":");
    const ex = REQ.headers.find((h) => h.name.toLowerCase() === n.toLowerCase());
    if (ex) { ex.value = v.join(":").trim(); ex.on = true; } else REQ.headers.push({ on: true, name: n, value: v.join(":").trim() });
    drawApiEdit();
  };
  ACT.apiFmt = () => {
    try { REQ.body = JSON.stringify(JSON.parse(REQ.body), null, 2); drawApiEdit(); } catch (e) { toast("Body isn't valid JSON: " + e.message); }
  };
  ACT.apiSend = () => {
    REQ.url = $("#api-url").value.trim();
    REQ.method = $("#api-m").value;
    if (!REQ.url) { $("#api-url").focus(); return; }
    if (apiBusy) return;
    apiBusy = true;
    reqId += 1;
    $("#api-send").textContent = "Sending…";
    $("#api-res").innerHTML = `<div class="loading">waiting for ${esc(host(REQ.url) || REQ.url)}</div>`;
    call("api.send", { id: reqId, method: REQ.method, url: REQ.url, headers: REQ.headers, body: REQ.body, timeout: REQ.timeout, followRedirects: REQ.follow });
  };
  function onApiResult(r) {
    apiBusy = false;
    $("#api-send") && ($("#api-send").textContent = "Send");
    apiRes = r;
    hist.unshift({ method: r.method, url: r.url, status: r.ok ? r.status : 0, headers: JSON.parse(JSON.stringify(REQ.headers)), body: REQ.body });
    hist.splice(30);
    drawRes();
    drawHist();
  }
  function hlJson(text) {
    return esc(text).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
      (m, str, colon, lit, num) => str ? (colon ? `<span class="j-key">${str}</span>${colon}` : `<span class="j-str">${str}</span>`)
        : lit ? `<span class="j-lit">${lit}</span>` : `<span class="j-num">${num}</span>`);
  }
  function drawRes() {
    const r = apiRes, box = $("#api-res");
    if (!r || !box) return;
    if (!r.ok) { box.innerHTML = `<div class="resp-meta"><span class="status s0">ERROR</span></div><pre class="out bad">${esc(r.error)}</pre>`; return; }
    let pretty = null;
    if (!r.binary && /json/i.test(r.contentType) || /^\s*[[{]/.test(r.body)) {
      try { pretty = JSON.stringify(JSON.parse(r.body), null, 2); } catch (e) { pretty = null; }
    }
    const cls = "s" + String(r.status)[0];
    box.innerHTML = `<div class="resp-meta"><span class="status ${cls}">${r.status} ${esc(r.reason)}</span>
        <span><b>${r.timeMs}</b> ms</span><span>first byte <b>${r.ttfbMs}</b> ms</span><span><b>${kb(r.size)}</b>${r.truncated ? " (cut at 2 MB)" : ""}</span>
        <span class="muted">${esc(r.contentType)}</span></div>
      <div class="subtabs" id="res-tabs">${[["body", "Body"], ["raw", "Raw"], ["headers", "Headers", r.headers.length], ["sent", "Sent"]].map(([k, l, n]) =>
        `<button data-act="resTab" data-k="${k}" class="${k === resTab ? "on" : ""}">${l}${n ? `<span class="count">${n}</span>` : ""}</button>`).join("")}
        <span class="grow"></span><button class="btn sm" data-act="copyRes" style="align-self:center">Copy</button></div>
      <div id="res-body"></div>`;
    const rb = $("#res-body");
    if (resTab === "body") rb.innerHTML = r.binary ? `<div class="empty">Binary response (${kb(r.size)}).</div>`
      : `<pre class="out">${pretty ? hlJson(pretty) : esc(r.body) || '<span class="muted">(empty body)</span>'}</pre>`;
    else if (resTab === "raw") rb.innerHTML = `<pre class="out">${esc(r.body) || '<span class="muted">(empty body)</span>'}</pre>`;
    else if (resTab === "headers") rb.innerHTML = `<table class="tbl">${r.headers.map(([k, v]) => `<tr><td class="mono" style="white-space:nowrap">${esc(k)}</td><td style="word-break:break-all">${esc(v)}</td></tr>`).join("")}</table>`;
    else rb.innerHTML = `<pre class="out">${esc(r.method + " " + r.finalUrl)}\n${r.sentHeaders.map(([k, v]) => esc(k + ": " + v)).join("\n")}</pre>`;
  }
  ACT.resTab = (b) => { resTab = b.dataset.k; drawRes(); };
  ACT.copyRes = () => apiRes && copy(resTab === "headers" ? apiRes.headers.map(([k, v]) => k + ": " + v).join("\n") : apiRes.body || apiRes.error || "", "Response copied");
  function drawHist() {
    const ul = $("#api-hist");
    if (!ul) return;
    ul.innerHTML = hist.length ? hist.map((h, i) => `<li data-act="histLoad" data-i="${i}"><span class="m">${esc(h.method)}</span><span class="u">${esc(h.url)}</span>
      <span class="status s${String(h.status)[0]}" style="font-size:10px">${h.status || "ERR"}</span></li>`).join("")
      : `<p class="note">Requests you send appear here.</p>`;
  }
  ACT.histLoad = (li) => {
    const h = hist[+li.dataset.i];
    loadRequest(h.method, h.url, h.headers, h.body);
  };
  function loadRequest(method, url, headers, body) {
    REQ.method = method || "GET"; REQ.url = url || ""; REQ.body = body || "";
    if (headers) REQ.headers = headers;
    $("#api-m").value = REQ.method;
    $("#api-url").value = REQ.url;
    drawApiEdit();
  }
  function curl() {
    const q = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'";
    let c = `curl -X ${REQ.method} ${q($("#api-url").value)}`;
    REQ.headers.filter((h) => h.on !== false && h.name).forEach((h) => { c += ` \\\n  -H ${q(h.name + ": " + h.value)}`; });
    if (REQ.body && !["GET", "HEAD"].includes(REQ.method)) c += ` \\\n  --data-raw ${q(REQ.body)}`;
    return c;
  }
  ACT.apiCurl = () => copy(curl(), "cURL command copied");
  ACT.apiSave = () => {
    const url = $("#api-url").value.trim();
    if (!url) return toast("Enter a URL first");
    call("bm.save", { kind: "endpoint", title: `${REQ.method} ${host(url) ? pathOf(url) : url}`.slice(0, 120), url, method: REQ.method,
                      content: JSON.stringify({ headers: REQ.headers, body: REQ.body }), tags: ["api"] });
    toast("Saved to dev bookmarks");
  };

  /* =========================================================== TERMINAL */
  const termHist = [];
  let termIdx = -1, termState = { cwd: "", shell: "", running: false, shells: [] };
  V.terminal = {
    init() {
      view("terminal").innerHTML = `
        <div class="term-bar">
          <select id="term-shell" data-change="termShell"></select>
          <div class="quick">${["git status", "git log --oneline -15", "git diff --stat", "git branch -a", "npm run", "npm test", "pip list", "python --version", "node --version"].map((c) =>
            `<button class="chip" data-act="termQuick" data-cmd="${esc(c)}">${esc(c)}</button>`).join("")}</div>
          <span class="grow"></span>
          <button class="btn sm" data-act="termCopy">Copy</button><button class="btn sm" data-act="termClear">Clear</button>
          <button class="btn sm danger" data-act="termKill" id="term-kill" disabled>Stop</button>
        </div>
        <pre class="term-out" id="term-out"><span class="sys">PRISM terminal: each command runs in your shell in the folder shown below.
cd changes folder, cls / clear clears, Ctrl+C stops a running command, ↑/↓ browse history.
Interactive full-screen programs (vim, less, htop) are not supported.
</span></pre>
        <div class="term-in"><span class="cwd" id="term-cwd" title=""></span><span class="ok">&gt;</span>
          <input type="text" id="term-input" spellcheck="false" autocomplete="off" placeholder="git status"><span class="run" id="term-run"></span></div>`;
      const inp = $("#term-input");
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const line = inp.value;
          if (!line.trim() && !termState.running) return;
          if (!termState.running) {
            append(`${termState.cwd}> ${line}\n`, "cmd");
            if (line.trim() && termHist[termHist.length - 1] !== line) termHist.push(line);
          }
          termIdx = -1;
          call("term.run", { line });
          inp.value = "";
        } else if (e.key === "ArrowUp" && termHist.length) {
          e.preventDefault();
          termIdx = termIdx < 0 ? termHist.length - 1 : Math.max(0, termIdx - 1);
          inp.value = termHist[termIdx];
        } else if (e.key === "ArrowDown" && termIdx >= 0) {
          e.preventDefault();
          termIdx = termIdx + 1 >= termHist.length ? -1 : termIdx + 1;
          inp.value = termIdx < 0 ? "" : termHist[termIdx];
        } else if (e.key === "c" && e.ctrlKey && termState.running && !inp.selectionEnd) {
          e.preventDefault(); call("term.interrupt");
        } else if (e.key === "c" && e.ctrlKey && termState.running && inp.selectionStart === inp.selectionEnd) {
          e.preventDefault(); call("term.interrupt");
        } else if (e.key === "l" && e.ctrlKey) {
          e.preventDefault(); ACT.termClear();
        }
      });
      $("#term-out").addEventListener("mouseup", () => { if (!getSelection().toString()) inp.focus(); });
    },
    head() { setHead(termState.cwd, ""); },
    update() {},
  };
  function append(text, cls) {
    const out = $("#term-out");
    if (!out) return;
    const atBottom = out.scrollTop + out.clientHeight >= out.scrollHeight - 20;
    const span = document.createElement("span");
    if (cls && cls !== "out") span.className = cls;
    span.textContent = text;
    out.appendChild(span);
    while (out.childNodes.length > 4000) out.removeChild(out.firstChild);
    if (atBottom || cls === "cmd") out.scrollTop = out.scrollHeight;
  }
  function onTerm(t) {
    if (t.stream === "clear") { ACT.termClear(); return; }
    if (t.stream === "close") { append("(use the panel's close button or Ctrl+` to hide the terminal)\n", "sys"); return; }
    if (t.text) append(t.text, t.stream);
  }
  function onTermState(s) {
    termState = s;
    if (!$("#term-cwd")) return;
    $("#term-cwd").textContent = s.cwd;
    $("#term-cwd").title = s.cwd;
    const sel = $("#term-shell"), shells = s.shells || [];
    if (sel.dataset.list !== JSON.stringify(shells)) {     // the OS's shells: cmd/PowerShell, or bash/zsh/...
      sel.dataset.list = JSON.stringify(shells);
      sel.innerHTML = shells.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
    }
    sel.value = s.shell;
    $("#term-kill").disabled = !s.running;
    $("#term-run").textContent = s.running ? `running: ${s.command.slice(0, 40)}` : "";
    $("#term-input").placeholder = s.running ? "input for the running program" : "git status";
    if (section === "terminal") setHead(s.cwd, "");
  }
  ACT.termQuick = (b) => { if (termState.running) return toast("A command is still running"); append(`${termState.cwd}> ${b.dataset.cmd}\n`, "cmd"); call("term.run", { line: b.dataset.cmd }); };
  ACT.termClear = () => { const o = $("#term-out"); if (o) o.innerHTML = ""; };
  ACT.termCopy = () => copy($("#term-out").textContent, "Output copied");
  ACT.termKill = () => call("term.interrupt");
  ACT.termShell = (s) => call("term.shell", { shell: s.value });

  /* ============================================================= MEMORY */
  V.memory = {
    head() { setHead(D.memory ? `${D.memory.tabs.length} tabs · updates every 2 s` : "", ""); },
    update(d) {
      if (d.error) { view("memory").innerHTML = `<div class="empty">${esc(d.error)}</div>`; return; }
      const max = Math.max(1, ...d.tabs.map((t) => (t.memory || {}).private || 0));
      const tabs = d.tabs.slice().sort((a, b) => ((b.memory || {}).private || 0) - ((a.memory || {}).private || 0));
      let h = `<div class="row" style="align-items:baseline;gap:10px"><span class="big">${mb(d.totalPrivate)}</span>
        <span class="muted">used by PRISM in total (private memory, all processes)</span></div>
        <p class="note">Each site runs in its own renderer process. Tabs on the same site share one, so their numbers are the same process.
          Discarding a background tab frees its memory; it reloads when you open it.</p>
        <h2>Tabs</h2>`;
      h += tabs.map((t) => {
        const m = t.memory;
        const p = m ? m.private : 0;
        return `<div class="memrow"><span class="dot" style="background:${esc(t.container.color)}"></span>
          <span class="t ${t.active ? "active" : ""}" title="${esc(t.url)}">${esc(t.title)}</span>
          <span class="acts">${!t.visible && !t.discarded ? `<button class="btn sm" data-act="memDiscard" data-id="${t.id}">Discard</button>` : ""}
            <button class="btn sm" data-act="memGo" data-id="${t.id}">Show</button><button class="x" data-act="memClose" data-id="${t.id}" title="Close tab">✕</button></span>
          <div class="meta"><span style="width:70px;color:var(--text)">${t.discarded ? "discarded" : mb(p)}</span>
            <span class="track"><span class="fill" style="display:block;width:${t.discarded ? 0 : (p / max) * 100}%"></span></span>
            <span>${t.pid ? `pid ${t.pid}` : "-"}${t.sharedWith > 1 ? ` · shared by ${t.sharedWith} tabs` : ""}${t.visible ? " · on screen" : ""}</span></div></div>`;
      }).join("");
      h += `<h2>Processes</h2><table class="tbl"><tr><th>pid</th><th>role</th><th class="num">private</th><th class="num">working set</th></tr>
        <tr><td>${"main"}</td><td>PRISM (Python + Qt)</td><td class="num">${mb((d.main || {}).private)}</td><td class="num">${mb((d.main || {}).workingSet)}</td></tr>
        ${d.processes.sort((a, b) => ((b.memory || {}).private || 0) - ((a.memory || {}).private || 0)).map((p) =>
          `<tr><td>${p.pid}</td><td>${esc(p.role)}</td><td class="num">${mb((p.memory || {}).private)}</td><td class="num">${mb((p.memory || {}).workingSet)}</td></tr>`).join("")}</table>`;
      view("memory").innerHTML = h;
    },
  };
  ACT.memDiscard = (b) => call("mem.discard", { id: +b.dataset.id });
  ACT.memGo = (b) => call("mem.activate", { id: +b.dataset.id });
  ACT.memClose = (b) => call("mem.close", { id: +b.dataset.id });

  /* ========================================================= CONTAINERS */
  V.containers = {
    init() {
      view("containers").innerHTML = `
        <p class="note">Each container is a separate identity: cookies, logins, local storage and cache never cross between them.
          Sites in Work can't see what you did in Personal. Container data lives in memory only and is gone when you close PRISM,
          unless you turn on <b>Remember logins</b> for that container. Then its cookies and site storage are kept on disk, in their own folder.
          Trackers and third-party cookies stay blocked either way, and history is never saved.</p>
        <div id="ct-list"></div>
        <h2>Disposable</h2>
        <div class="box stack">
          <div class="row"><span class="grow"><b>Temporary session</b><div class="muted" style="font-size:11px">A fresh container that is destroyed, with all its data, when its last tab closes.</div></span>
            <button class="btn" data-act="ctTemp">New session</button></div>
          <div><b>Sandbox</b><div class="muted" style="font-size:11px;margin:2px 0 6px">For links you don't trust: scripts off, every third-party request blocked, no downloads, no permissions, no site storage.</div>
            <div class="row"><input type="text" id="sb-url" class="grow" placeholder="URL to open in a sandbox (empty = current page)"><button class="btn" data-act="ctSandbox">Open</button></div></div>
        </div>
        <div id="ct-move"></div>`;
      $("#sb-url").addEventListener("keydown", (e) => { if (e.key === "Enter") ACT.ctSandbox(); });
    },
    head() { setHead("isolated sessions", ""); },
    update(d) {
      $("#ct-list").innerHTML = d.containers.map((c) => `<div class="ct" style="--cc:${esc(c.color)}"><span class="stripe"></span>
        <div><div class="name">${esc(c.name)} ${c.kind !== "standard" ? `<span class="badge">${esc(c.kind)}</span>` : ""}</div>
          <div class="meta">${c.tabs} tab(s) · ${c.cookies} cookie(s) from ${c.sites} site(s)${c.active ? "" : " · not started"}</div>
          ${c.kind === "standard" ? `<label class="tg ct-remember" title="Keep this container's cookies and site storage on disk, so you stay signed in after closing PRISM">
            <span class="sw"><input type="checkbox" data-change="ctRemember" data-id="${esc(c.id)}" ${c.remember ? "checked" : ""}><i></i></span>Remember logins</label>` : ""}</div>
        <div class="acts"><button class="btn sm" data-act="ctOpen" data-id="${esc(c.id)}">New tab</button>
          ${c.tabs ? `<button class="btn sm" data-act="ctClose" data-id="${esc(c.id)}">Close tabs</button>` : ""}
          ${c.active && c.kind === "standard" ? `<button class="btn sm danger" data-act="ctClear" data-id="${esc(c.id)}"
            title="${c.remember ? "Erase this container's saved logins and site storage" : "Delete this container's cookies and cache"}">${c.remember ? "Forget logins" : "Clear data"}</button>` : ""}</div></div>`).join("");
      const cur = d.current;
      $("#ct-move").innerHTML = cur ? `<h2>This tab <small>${esc(cur.name)}</small></h2><div class="chips">${d.containers.filter((c) => c.kind === "standard" && c.id !== cur.id).map((c) =>
        `<button class="chip" data-act="ctMove" data-id="${esc(c.id)}" style="border-color:${esc(c.color)}">Reopen in ${esc(c.name)}</button>`).join("")}</div>` : "";
    },
  };
  ACT.ctOpen = (b) => call("ct.open", { id: b.dataset.id });
  ACT.ctClose = (b) => call("ct.closeAll", { id: b.dataset.id });
  ACT.ctClear = (b) => call("ct.clear", { id: b.dataset.id });
  ACT.ctRemember = (el) => call("ct.remember", { id: el.dataset.id, on: el.checked });
  ACT.ctMove = (b) => call("ct.move", { id: b.dataset.id });
  ACT.ctTemp = () => call("ct.temp");
  ACT.ctSandbox = () => { call("ct.sandbox", { url: $("#sb-url").value }); $("#sb-url").value = ""; };

  /* ======================================================== PERMISSIONS */
  /* ========================================================== DOWNLOADS */
  V.downloads = {
    head() {
      const n = D.downloads ? D.downloads.items.filter((i) => i.state === "progress").length : 0;
      setHead(n ? `${n} in progress` : "this session",
        `<button class="btn sm" data-act="dlOpenFile" title="Open a PDF, HTML page or other file in PRISM (Ctrl+O)">Open file…</button>`);
    },
    update(d) {
      if (d.error) { view("downloads").innerHTML = `<div class="empty">${esc(d.error)}</div>`; return; }
      V.downloads.head();
      const modes = Object.entries(d.modes);
      let h = `<h2>When a download starts</h2>
        <div class="seg">${modes.map(([k, l]) => `<button data-act="dlMode" data-v="${k}" class="${d.mode === k ? "on" : ""}">${esc(l)}</button>`).join("")}</div>
        <p class="note">${d.mode === "ask" ? "PRISM asks where to save each file: rename it, pick a folder, or browse for any folder."
          : d.mode === "system" ? "Each download opens your system's Save As dialog."
          : "Files go straight into the default folder, no questions asked."}</p>
        <div class="box row"><span class="grow" style="overflow-wrap:anywhere"><span class="muted" style="font-size:11px">Default folder</span><br>${esc(d.dir)}</span>
          <button class="btn sm" data-act="dlOpenFolder">Open</button><button class="btn sm" data-act="dlFolder">Change…</button></div>`;
      const done = d.items.some((i) => i.state !== "progress");
      h += `<h2><span class="grow">Files <small>${d.items.length}</small></span>${done ? `<button class="btn sm" data-act="dlClear">Clear finished</button>` : ""}</h2>`;
      h += d.items.length ? d.items.map((i) => {
        const pct = i.total > 0 ? Math.min(100, (i.received / i.total) * 100) : (i.state === "done" ? 100 : 0);
        const status = i.state === "progress" ? `${kb(i.received)}${i.total > 0 ? " of " + kb(i.total) : ""}`
          : i.state === "done" ? `${kb(i.received)} · ${esc(i.source)}` : i.state;
        const acts = i.state === "progress" ? `<button class="btn sm" data-act="dlCancel" data-id="${i.id}">Cancel</button>`
          : i.state === "done" ? `<button class="btn sm" data-act="dlOpen" data-id="${i.id}">Open</button>
              <button class="btn sm" data-act="dlReveal" data-id="${i.id}">Show in folder</button>` : "";
        return `<div class="memrow dlrow"><span class="dot" style="background:var(${i.state === "done" ? "--green" : i.state === "progress" ? "--green-dim" : "--danger"})"></span>
          <span class="t" title="${esc(i.path)}">${esc(i.name)}</span><span class="acts">${acts}</span>
          <div class="meta"><span class="track"><span class="fill ${i.state === "done" ? "done" : i.state === "progress" ? "" : "bad"}" style="display:block;width:${pct}%"></span></span>
            <span>${status}</span></div></div>`;
      }).join("") : `<div class="empty"><b>No downloads yet</b>Downloads from this session show up here. PDFs, pages and images open right in PRISM; use Open file… for files on your computer.</div>`;
      view("downloads").innerHTML = h;
    },
  };
  ACT.dlMode = (b) => call("dl.mode", { mode: b.dataset.v });
  ACT.dlFolder = () => call("dl.folder");
  ACT.dlOpenFolder = () => call("dl.openFolder");
  ACT.dlOpenFile = () => call("dl.openFile");
  ACT.dlOpen = (b) => call("dl.open", { id: +b.dataset.id });
  ACT.dlReveal = (b) => call("dl.reveal", { id: +b.dataset.id });
  ACT.dlCancel = (b) => call("dl.cancel", { id: +b.dataset.id });
  ACT.dlClear = () => call("dl.clear");

  V.permissions = {
    head() { setHead(D.permissions ? `${fmt(D.permissions.denied)} requests denied in total` : "", ""); },
    update(d) {
      const pol = (cur, act, extra) => `<div class="seg">${[["ask", "Ask", "a"], ["allow", "Allow", ""], ["block", "Block", "b"]].map(([v, l, c]) =>
        `<button data-act="${act}" data-v="${v}" ${extra} class="${cur === v ? "on " + c : ""}">${l}</button>`).join("")}</div>`;
      let h = "";
      if (d.pending.length) {
        h += `<h2>Waiting for you</h2>` + d.pending.map((p) => `<div class="box row wrap"><span class="grow"><b>${esc(p.site)}</b> wants ${esc(p.label.toLowerCase())}
          <div class="muted" style="font-size:11px">in tab: ${esc(p.tabTitle)}</div></span>
          <button class="btn sm primary" data-act="permAnswer" data-id="${p.id}" data-allow="1">Allow</button>
          <button class="btn sm" data-act="permAnswer" data-id="${p.id}" data-allow="">Block</button></div>`).join("");
      }
      h += `<h2>Defaults <small>for every site</small></h2><table class="tbl">${d.types.map((t) =>
        `<tr><td>${esc(t.label)}</td><td style="text-align:right">${pol(t.policy, "permDefault", `data-type="${t.type}"`)}</td></tr>`).join("")}</table>
        <p class="note">Sandbox tabs are always denied everything. Temporary sessions and containers share these rules.</p>`;
      const sites = Object.entries(d.sites);
      h += `<h2>Site exceptions <small>${sites.length}</small></h2>`;
      h += sites.length ? sites.map(([site, rules]) => `<div class="box"><div class="row"><b class="grow">${esc(site)}</b>
          <button class="btn sm" data-act="permClear" data-site="${esc(site)}">Remove all</button></div>
          ${Object.entries(rules).map(([type, p]) => `<div class="row" style="padding:3px 0"><span class="grow">${esc(INIT.permissionTypes[type] || type)}</span>
            <span class="badge ${p === "allow" ? "ok" : "bad"}">${p}</span><button class="x" data-act="permSiteDel" data-site="${esc(site)}" data-type="${type}">✕</button></div>`).join("")}</div>`).join("")
        : `<p class="note">No exceptions. Tick "remember" on a permission prompt, or use the Site tab, to add one.</p>`;
      view("permissions").innerHTML = h;
    },
  };
  ACT.permDefault = (b) => call("perm.default", { type: b.dataset.type, policy: b.dataset.v });
  ACT.permClear = (b) => call("perm.clearSite", { site: b.dataset.site });
  ACT.permSiteDel = (b) => call("perm.site", { site: b.dataset.site, type: b.dataset.type, policy: null });
  ACT.permAnswer = (b) => call("perm.answer", { id: b.dataset.id, allow: !!b.dataset.allow, remember: false });

  /* ============================================================== VAULT */
  let vEdit = null, vReveal = {}, vFilter = "";
  V.vault = {
    head() {
      setHead(D.vault && D.vault.unlocked ? `${D.vault.entries.length} login(s) · locks after 5 min idle` : "encrypted on this computer",
        D.vault && D.vault.unlocked ? `<button class="btn sm" data-act="vLock">Lock</button>` : "");
    },
    update(d) {
      const el = view("vault");
      V.vault.head();
      if (!d.exists) {
        el.innerHTML = `<p class="note">Store logins encrypted with AES-256-GCM under a master password (scrypt key derivation).
          The vault file never leaves this computer and is unreadable without the master password. It can't be recovered if you forget it.</p>
          <div class="form box"><label>Master password (10+ characters)<input type="password" id="v-new1" autocomplete="new-password"></label>
            <div class="meter"><i id="v-meter"></i></div>
            <label>Repeat it<input type="password" id="v-new2" autocomplete="new-password"></label>
            <div class="row"><span class="grow bad" id="v-err"></span><button class="btn primary" data-act="vCreate">Create vault</button></div></div>`;
        $("#v-new1").addEventListener("input", (e) => meter(e.target.value));
        return;
      }
      if (!d.unlocked) {
        el.innerHTML = `<div class="form box"><label>Master password<input type="password" id="v-pw" autocomplete="current-password"></label>
          <div class="row"><span class="grow bad" id="v-err"></span><button class="btn primary" data-act="vUnlock">Unlock</button></div></div>
          <p class="note">Stored at ${esc(d.path)}</p>`;
        const pw = $("#v-pw");
        pw.addEventListener("keydown", (e) => { if (e.key === "Enter") ACT.vUnlock(); });
        setTimeout(() => pw.focus(), 0);
        return;
      }
      const match = new Set(d.forSite || []);
      const list = d.entries.filter((e) => !vFilter || (e.site + " " + e.username).toLowerCase().includes(vFilter))
        .sort((a, b) => (match.has(b.id) - match.has(a.id)));
      let h = `<div class="row"><input type="search" id="v-q" class="grow" placeholder="search logins" value="${esc(vFilter)}">
        <button class="btn primary" data-act="vNew">+ Add login</button></div>`;
      if (vEdit) h += editor(vEdit, d.host);
      h += list.length ? list.map((e) => `<div class="entry ${match.has(e.id) ? "match" : ""}"><div class="site">${esc(e.site)}</div>
          <div class="user">${esc(e.username || "(no username)")}${vReveal[e.id] ? ` · <span class="secret">${esc(vReveal[e.id])}</span>` : ""}</div>
          <div class="acts">${match.has(e.id) ? `<button class="btn sm primary" data-act="vaultFill" data-id="${e.id}">Fill</button>` : ""}
            <button class="btn sm" data-act="vCopy" data-id="${e.id}" data-f="username" title="Copy username">User</button>
            <button class="btn sm" data-act="vCopy" data-id="${e.id}" data-f="password" title="Copy password (clipboard clears in 20 s)">Pass</button>
            <button class="btn sm" data-act="vReveal" data-id="${e.id}">${vReveal[e.id] ? "Hide" : "Show"}</button>
            <button class="btn sm" data-act="vEditBtn" data-id="${e.id}">Edit</button></div></div>`).join("")
        : `<div class="empty"><b>${d.entries.length ? "No match" : "No logins yet"}</b>${d.entries.length ? "" : "Add one, or open a login page and add it from there."}</div>`;
      h += `<details style="margin-top:16px"><summary class="muted">Change master password</summary><div class="form box" style="margin-top:8px">
        <label>Current<input type="password" id="v-old"></label><label>New (10+ characters)<input type="password" id="v-n1"></label>
        <div class="row"><span class="grow bad" id="v-err2"></span><button class="btn" data-act="vChange">Change</button></div></div></details>`;
      el.innerHTML = h;
      const q = $("#v-q");
      q.addEventListener("input", () => { vFilter = q.value.toLowerCase(); const pos = q.selectionStart; V.vault.update(D.vault); const nq = $("#v-q"); nq.focus(); nq.setSelectionRange(pos, pos); });
    },
  };
  function editor(e, curHost) {
    return `<div class="form box" style="margin-top:10px">
      <label>Site<input type="text" id="ve-site" value="${esc(e.site || curHost || "")}" placeholder="github.com"></label>
      <label>Username or email<input type="text" id="ve-user" value="${esc(e.username || "")}"></label>
      <label>Password<div class="row"><input type="password" id="ve-pw" value="${esc(e.password || "")}" placeholder="${e.id ? "unchanged unless you type" : ""}">
        <button class="btn sm" data-act="vToggle">Show</button><button class="btn sm" data-act="vGen">Generate</button></div></label>
      <label>Notes<textarea id="ve-notes" rows="2">${esc(e.notes || "")}</textarea></label>
      <div class="row"><span class="grow bad" id="v-err"></span>${e.id ? `<button class="btn sm danger" data-act="vDel" data-id="${e.id}">Delete</button>` : ""}
        <button class="btn" data-act="vCancel">Cancel</button><button class="btn primary" data-act="vSave">Save</button></div></div>`;
  }
  function meter(pw) {
    const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^\w]/].filter((r) => r.test(pw)).length;
    const score = Math.min(100, pw.length * 4 + classes * 10);
    const m = $("#v-meter");
    if (m) { m.style.width = score + "%"; m.style.background = score > 75 ? "var(--green)" : score > 45 ? "var(--warn)" : "var(--danger)"; }
  }
  const vErr = (msg) => { const e = $("#v-err") || $("#v-err2"); if (e) e.textContent = msg; else toast(msg); };
  ACT.vCreate = () => {
    const a = $("#v-new1").value, b = $("#v-new2").value;
    if (a !== b) return vErr("The passwords don't match.");
    call("vault.create", { password: a });
  };
  ACT.vUnlock = () => { vErr(""); call("vault.unlock", { password: $("#v-pw").value }); };
  ACT.vLock = () => { vReveal = {}; vEdit = null; call("vault.lock"); };
  ACT.vNew = () => { vEdit = {}; V.vault.update(D.vault); $("#ve-user").focus(); };
  ACT.vEditBtn = (b) => {
    const e = D.vault.entries.find((x) => x.id === b.dataset.id);
    vEdit = { ...e, password: "" };
    call("vault.reveal", { id: e.id, forEdit: true });
    V.vault.update(D.vault);
  };
  ACT.vCancel = () => { vEdit = null; V.vault.update(D.vault); };
  ACT.vToggle = (b) => { const i = $("#ve-pw"); i.type = i.type === "password" ? "text" : "password"; b.textContent = i.type === "password" ? "Show" : "Hide"; };
  ACT.vGen = () => call("vault.generate", { length: 20, symbols: true, target: "editor" });
  ACT.vSave = () => {
    const entry = { id: vEdit.id, site: $("#ve-site").value, username: $("#ve-user").value, password: $("#ve-pw").value, notes: $("#ve-notes").value };
    if (vEdit.id && !entry.password) entry.password = vEdit.password;
    vEdit = null;
    call("vault.save", entry);
  };
  ACT.vDel = (b) => { if (b.dataset.confirm) { vEdit = null; call("vault.delete", { id: b.dataset.id }); } else { b.dataset.confirm = "1"; b.textContent = "Really delete?"; } };
  ACT.vCopy = (b) => call("vault.copy", { id: b.dataset.id, field: b.dataset.f });
  ACT.vReveal = (b) => {
    if (vReveal[b.dataset.id]) { delete vReveal[b.dataset.id]; V.vault.update(D.vault); } else call("vault.reveal", { id: b.dataset.id });
  };
  ACT.vChange = () => call("vault.changePassword", { old: $("#v-old").value, new: $("#v-n1").value });

  /* ============================================================= DESIGN */
  let dzSev = "all", dzFocus = "", dzTick = null;
  const SEV = { high: "bad", medium: "warn", low: "ok" };
  const CRED = { saved: "saved key (encrypted with Windows DPAPI)", session: "key pasted this session",
                 environment: "ANTHROPIC_API_KEY from the environment", sdk: "`ant auth login` profile, if there is one" };
  function dzKeyForm(d) {
    return `<div class="form box">
      <label>Anthropic API key<input type="password" id="dz-key" autocomplete="off" spellcheck="false" placeholder="sk-ant-…"></label>
      <div class="row"><span class="grow muted">${d.canSave ? "Saved encrypted with Windows DPAPI." : "Kept in memory until PRISM closes."}</span>
        <button class="btn primary" data-act="dzKey">Save key</button></div></div>`;
  }
  V.design = {
    head() {
      const d = D.design;
      const busy = d && d.status === "working";
      setHead(busy ? "reviewing…" : d && d.status === "done" ? `${d.issues.length} issue${d.issues.length === 1 ? "" : "s"} · ${host(d.url)}` : "Claude · " + (d ? d.model : ""),
        `<button class="btn sm primary" data-act="dzReview" ${busy ? "disabled" : ""}>${busy ? "Reviewing…" : "Review this page"}</button>`);
    },
    update(d) {
      V.design.head();
      const el = view("design");
      const focusEl = $("#dz-focus");
      if (focusEl) dzFocus = focusEl.value;
      const cur = d.current;
      let h = `<p class="note">Claude (${esc(d.model)}, Anthropic's hosted API) looks at a screenshot of this tab and at measurements
        PRISM takes from the page (fonts, colors, contrast, spacing, tap targets, overflow, images, headings), then lists what to fix.
        <b>Nothing is sent until you press Review</b>, and then only the screenshot and the measurements go to api.anthropic.com.
        Form values, cookies and storage are never read. Use the responsive preview (Ctrl+Shift+M) first to review a mobile layout.</p>`;
      h += `<div class="form box"><label>Focus <span class="muted">(optional)</span>
          <input type="text" id="dz-focus" value="${esc(dzFocus)}" placeholder="e.g. the pricing cards, mobile nav, dark mode"></label>
        <div class="row"><span class="grow muted">${cur ? esc(cur.title || host(cur.url)) : "No web page in this tab"}</span>
        <button class="btn primary" data-act="dzReview" ${d.status === "working" || !cur || d.sandbox ? "disabled" : ""}>${d.status === "working" ? "Reviewing…" : "Review this page"}</button></div>
        ${d.sandbox ? `<p class="note warn">Sandbox tabs are never sent anywhere.</p>` : ""}</div>`;

      if (d.status === "working") {
        h += `<div class="empty"><b><span class="dz-spin"></span> Claude is reviewing ${esc(host(d.url))}…</b>
          <span id="dz-elapsed">${Math.round((Date.now() - d.startedAt) / 1000)} s</span> · a thorough review usually takes 20 to 90 seconds.</div>`;
      } else if (d.status === "error") {
        h += `<div class="box"><p class="note bad">${esc(d.error)}</p></div>`;
      } else if (d.status === "done") {
        const stale = cur && cur.url !== d.url;
        const counts = { high: 0, medium: 0, low: 0 };
        d.issues.forEach((i) => { counts[i.severity] = (counts[i.severity] || 0) + 1; });
        h += `<h2>Summary <small>${esc(host(d.url))}${stale ? ' · <span class="warn">from another page</span>' : ""}</small></h2>
          <div class="box"><p style="margin:0;line-height:1.6">${esc(d.summary)}</p></div>
          <div class="chips" id="dz-sev" style="margin:12px 0 8px">${[["all", `All ${d.issues.length}`], ["high", `High ${counts.high}`],
            ["medium", `Medium ${counts.medium}`], ["low", `Low ${counts.low}`]].map(([k, l]) =>
            `<button class="chip ${dzSev === k ? "on" : ""}" data-act="dzSev" data-k="${k}">${l}</button>`).join("")}</div>`;
        const list = d.issues.filter((i) => dzSev === "all" || i.severity === dzSev);
        h += list.length ? list.map((i) => `<div class="dz-issue sev-${esc(i.severity)}">
            <div class="row"><span class="badge ${SEV[i.severity] || ""}">${esc(i.severity)}</span>
              <span class="badge">${esc(i.category)}</span><b class="grow">${esc(i.title)}</b>
              ${i.selector && !stale ? `<button class="btn sm" data-act="dzShow" data-sel="${esc(i.selector)}" title="${esc(i.selector)}">Show</button>` : ""}</div>
            <p>${esc(i.detail)}</p>
            <div class="dz-fix"><span class="muted">fix</span> ${esc(i.fix)}
              <button class="btn sm" data-act="dzCopy" data-text="${esc(i.fix)}">Copy</button></div>
            ${i.selector ? `<div class="sub2 muted mono">${esc(i.selector)}</div>` : ""}</div>`).join("")
          : `<div class="empty">Nothing at this severity.</div>`;
        h += `<p class="note">Served by ${esc(d.servedBy)} in ${d.seconds} s · ${fmt(d.usage.input)} tokens in, ${fmt(d.usage.output)} out
          ${d.requestId ? `· request ${esc(d.requestId)}` : ""}. AI review can be wrong: check each issue before you change code.</p>`;
      }

      h += `<details style="margin-top:16px" ${d.needsKey ? "open" : ""}><summary class="muted">API key · using ${esc(CRED[d.credentials] || d.credentials)}</summary>
        <div style="margin-top:8px">${dzKeyForm(d)}
        ${d.credentials === "saved" || d.credentials === "session" ? `<div class="row" style="margin-top:8px"><span class="grow"></span>
          <button class="btn danger sm" data-act="dzForget">Forget key</button></div>` : ""}
        <p class="note">Without a pasted key PRISM uses ANTHROPIC_API_KEY or an <code>ant auth login</code> profile.
          Usage is billed to that Anthropic account.</p></div></details>`;
      el.innerHTML = h;

      clearInterval(dzTick);
      if (d.status === "working") dzTick = setInterval(() => {
        const e = $("#dz-elapsed");
        if (e && D.design) e.textContent = Math.round((Date.now() - D.design.startedAt) / 1000) + " s"; else clearInterval(dzTick);
      }, 1000);
    },
  };
  ACT.dzReview = () => {
    const f = $("#dz-focus");
    if (f) dzFocus = f.value;
    dzSev = "all";
    call("design.review", { focus: dzFocus });
  };
  ACT.dzSev = (b) => { dzSev = b.dataset.k; V.design.update(D.design); };
  ACT.dzShow = (b) => call("design.highlight", { selector: b.dataset.sel });
  ACT.dzCopy = (b) => copy(b.dataset.text, "Fix copied");
  ACT.dzKey = () => { const k = $("#dz-key"); call("design.key", { key: k.value }); k.value = ""; };
  ACT.dzForget = (b) => {
    if (b.dataset.confirm) call("design.forgetKey");
    else { b.dataset.confirm = "1"; b.textContent = "Really forget?"; }
  };

  /* ========================================================== BOOKMARKS */
  let bmKind = "all", bmQ = "", bmEdit = null;
  const KINDS = { link: "Link", doc: "Docs", endpoint: "API endpoint", snippet: "Snippet", note: "Note" };
  V.bookmarks = {
    init() {
      view("bookmarks").innerHTML = `
        <div class="row wrap" style="margin-bottom:8px">
          <button class="btn primary" data-act="bmCurrent">+ This page</button>
          <button class="btn" data-act="bmNew" data-kind="snippet">+ Snippet</button>
          <button class="btn" data-act="bmNew" data-kind="endpoint">+ Endpoint</button>
          <button class="btn" data-act="bmNew" data-kind="note">+ Note</button></div>
        <div class="row" style="margin-bottom:8px"><input type="search" id="bm-q" class="grow" placeholder="search titles, URLs, code, tags"></div>
        <div class="chips" id="bm-kinds" style="margin-bottom:6px">${[["all", "All"], ...Object.entries(KINDS)].map(([k, l]) =>
          `<button class="chip ${k === bmKind ? "on" : ""}" data-k="${k}">${l}</button>`).join("")}</div>
        <div id="bm-edit"></div><div id="bm-list"></div>`;
      $("#bm-q").addEventListener("input", (e) => { bmQ = e.target.value.toLowerCase(); drawBm(); });
      $("#bm-kinds").addEventListener("click", (e) => {
        const b = e.target.closest("[data-k]");
        if (!b) return;
        bmKind = b.dataset.k;
        $$("#bm-kinds .chip").forEach((c) => c.classList.toggle("on", c === b));
        drawBm();
      });
    },
    head() { setHead(D.bookmarks ? `${D.bookmarks.items.length} saved · stored locally` : "", ""); },
    update() { drawBm(); },
  };
  function drawBm() {
    const d = D.bookmarks;
    if (!d || !$("#bm-list")) return;
    $("#bm-edit").innerHTML = bmEdit ? bmEditor(bmEdit) : "";
    const items = d.items.filter((i) => (bmKind === "all" || i.kind === bmKind) &&
      (!bmQ || [i.title, i.url, i.content, i.tags.join(" ")].join(" ").toLowerCase().includes(bmQ)));
    $("#bm-list").innerHTML = items.length ? items.map((i) => `<div class="bm"><div class="top">
        <span class="badge k-${i.kind}">${KINDS[i.kind]}</span>
        <span class="title" data-act="bmOpen" data-id="${i.id}" title="${esc(i.url || i.title)}">${esc(i.title)}</span>
        ${i.kind === "endpoint" ? `<button class="btn sm" data-act="bmApi" data-id="${i.id}">Open in API tester</button>` : ""}
        ${i.content && i.kind !== "endpoint" ? `<button class="btn sm" data-act="bmCopy" data-id="${i.id}">Copy</button>` : ""}
        <button class="btn sm" data-act="bmEditBtn" data-id="${i.id}">Edit</button></div>
        ${i.url ? `<div class="sub2">${i.kind === "endpoint" ? `<b class="ok">${esc(i.method)}</b> ` : ""}${esc(i.url)}</div>` : ""}
        ${i.kind === "snippet" || i.kind === "note" ? `<pre class="out">${esc(i.content.slice(0, 1500))}${i.content.length > 1500 ? "\n…" : ""}</pre>` : ""}
        ${i.tags.length || i.lang ? `<div class="tags">${i.lang ? `<span>${esc(i.lang)}</span>` : ""}${i.tags.map((t) => `<span>#${esc(t)}</span>`).join("")}</div>` : ""}</div>`).join("")
      : `<div class="empty"><b>${d.items.length ? "Nothing matches" : "No bookmarks yet"}</b>${d.items.length ? "" : "Save docs pages, API endpoints, code snippets and notes you keep coming back to."}</div>`;
  }
  function bmEditor(i) {
    const code = i.kind === "snippet" || i.kind === "note";
    return `<div class="form box" style="margin-bottom:10px">
      <div class="row"><select id="be-kind">${Object.entries(KINDS).map(([k, l]) => `<option value="${k}" ${i.kind === k ? "selected" : ""}>${l}</option>`).join("")}</select>
        <input type="text" id="be-title" class="grow" placeholder="Title" value="${esc(i.title || "")}"></div>
      ${i.kind === "endpoint" ? `<div class="row"><select id="be-method">${["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => `<option ${i.method === m ? "selected" : ""}>${m}</option>`).join("")}</select>
        <input type="text" id="be-url" class="grow" placeholder="https://api.example.com/v1/…" value="${esc(i.url || "")}"></div>`
        : !code ? `<input type="text" id="be-url" placeholder="URL" value="${esc(i.url || "")}">` : ""}
      ${code ? `<textarea id="be-content" rows="8" spellcheck="false" placeholder="${i.kind === "snippet" ? "code" : "note"}">${esc(i.content || "")}</textarea>` : ""}
      <div class="row">${i.kind === "snippet" ? `<input type="text" id="be-lang" placeholder="language" value="${esc(i.lang || "")}" style="width:110px">` : ""}
        <input type="text" id="be-tags" class="grow" placeholder="tags, comma separated" value="${esc((i.tags || []).join(", "))}"></div>
      <div class="row"><span class="grow"></span>${i.id ? `<button class="btn sm danger" data-act="bmDel" data-id="${i.id}">Delete</button>` : ""}
        <button class="btn" data-act="bmCancel">Cancel</button><button class="btn primary" data-act="bmSave">Save</button></div></div>`;
  }
  ACT.bmNew = (b) => { bmEdit = { kind: b.dataset.kind, title: "", tags: [] }; drawBm(); $("#be-title").focus(); };
  ACT.bmCurrent = () => {
    const c = D.bookmarks && D.bookmarks.current;
    if (!c) return toast("Open a web page first");
    const docs = /docs|developer|reference|api|manual|readthedocs|mdn|devdocs/i.test(c.url);
    bmEdit = { kind: docs ? "doc" : "link", title: c.title, url: c.url, tags: [] };
    drawBm();
    $("#be-title").focus();
  };
  ACT.bmEditBtn = (b) => { bmEdit = { ...D.bookmarks.items.find((i) => i.id === b.dataset.id) }; drawBm(); };
  ACT.bmCancel = () => { bmEdit = null; drawBm(); };
  ACT.bmSave = () => {
    const kind = $("#be-kind").value;
    const item = { id: bmEdit.id, kind, title: $("#be-title").value,
      url: $("#be-url") ? $("#be-url").value : bmEdit.url || "", method: $("#be-method") ? $("#be-method").value : bmEdit.method || "GET",
      content: $("#be-content") ? $("#be-content").value : bmEdit.content || "", lang: $("#be-lang") ? $("#be-lang").value : bmEdit.lang || "",
      tags: $("#be-tags").value.split(",").map((t) => t.trim()).filter(Boolean) };
    bmEdit = null;
    call("bm.save", item);
  };
  document.addEventListener("change", (e) => {
    if (e.target.id === "be-kind" && bmEdit) { bmEdit = { ...bmEdit, kind: e.target.value, title: $("#be-title").value }; drawBm(); }
  });
  ACT.bmDel = (b) => { if (b.dataset.confirm) { bmEdit = null; call("bm.delete", { id: b.dataset.id }); } else { b.dataset.confirm = "1"; b.textContent = "Really delete?"; } };
  ACT.bmOpen = (b) => {
    const i = D.bookmarks.items.find((x) => x.id === b.dataset.id);
    if (i.kind === "endpoint") return ACT.bmApi(b);
    if (i.url) call("bm.open", { url: i.url }); else { bmEdit = { ...i }; drawBm(); }
  };
  ACT.bmCopy = (b) => { const i = D.bookmarks.items.find((x) => x.id === b.dataset.id); copy(i.content || i.url, "Copied"); };
  ACT.bmApi = (b) => {
    const i = D.bookmarks.items.find((x) => x.id === b.dataset.id);
    let extra = {};
    try { extra = JSON.parse(i.content || "{}"); } catch (e) { extra = {}; }
    show("api");
    loadRequest(i.method, i.url, extra.headers, extra.body);
  };

  /* ===================================================== push handlers */
  const ON = {
    init(d) {
      INIT = d;
      // Sections this edition of PRISM leaves out (see edition.py) are removed,
      // along with any separator left dangling.
      $$(".rail button[data-sec]").forEach((b) => {
        if (!d.sections.includes(b.dataset.sec)) { b.remove(); const v = view(b.dataset.sec); if (v) v.remove(); }
      });
      $$(".rail .sep").forEach((sep) => {
        const next = sep.nextElementSibling;
        if (!next || next.classList.contains("sep")) sep.remove();
      });
      Object.keys(TITLES).forEach((k) => { if (!d.sections.includes(k)) delete TITLES[k]; });
    },
    open(d) {
      show(d.section, false);
      if (d.focus) setTimeout(() => {
        const f = d.section === "terminal" ? $("#term-input") : d.section === "api" ? $("#api-url") : null;
        if (f) f.focus();
      }, 30);
    },
    toast(d) { toast(d.text); },
    site(d) { D.site = d; if (section === "site") { V.site.head(); V.site.update(d); } },
    network(d) { D.network = d; if (section === "network" && V.network.ready) { V.network.head(); V.network.update(d); } },
    source(d) {
      const changed = !D.source || D.source.url !== d.url;
      D.source = d;
      if (changed) { D.sourceHtml = null; D.sourceMeta = null; }
      if (section === "source") { V.source.head(); drawSource(); }
    },
    sourceHtml(d) { D.sourceHtml = d; if (section === "source") { V.source.head(); drawSource(); } },
    sourceMeta(d) { D.sourceMeta = d; if (section === "source" && srcTab === "meta") drawSource(); },
    api(d) { onApiResult(d); },
    term(d) { onTerm(d); },
    termState(d) { onTermState(d); },
    downloads(d) { D.downloads = d; if (section === "downloads") V.downloads.update(d); },
    memory(d) { D.memory = d; if (section === "memory") { V.memory.head(); V.memory.update(d); } },
    containers(d) { D.containers = d; if (section === "containers" && V.containers.ready) V.containers.update(d); },
    permissions(d) {
      D.permissions = d;
      const dot = $('.rail button[data-sec="permissions"] .dot');
      if (d.pending.length && !dot) $('.rail button[data-sec="permissions"]').insertAdjacentHTML("beforeend", '<i class="dot"></i>');
      if (!d.pending.length && dot) dot.remove();
      if (section === "permissions") { V.permissions.head(); V.permissions.update(d); }
    },
    vault(d) { D.vault = d; if (section === "vault") V.vault.update(d); },
    vaultError(d) { vErr(d.message); },
    vaultSecret(d) {
      if (vEdit && vEdit.id === d.id) { vEdit.password = d.password; return; }
      vReveal[d.id] = d.password;
      if (section === "vault") V.vault.update(D.vault);
      setTimeout(() => { delete vReveal[d.id]; if (section === "vault" && D.vault) V.vault.update(D.vault); }, 15000);
    },
    vaultGenerated(d) {
      const i = $("#ve-pw");
      if (i) { i.value = d.password; i.type = "text"; }
    },
    bookmarks(d) { D.bookmarks = d; if (section === "bookmarks" && V.bookmarks.ready) { V.bookmarks.head(); drawBm(); } },
    design(d) {
      const typing = document.activeElement && ["dz-focus", "dz-key"].includes(document.activeElement.id);
      const same = D.design && D.design.status === d.status && D.design.startedAt === d.startedAt && D.design.credentials === d.credentials;
      D.design = d;
      // The live refresh only changes "current"; don't redraw under someone typing.
      if (section === "design" && !(typing && same)) V.design.update(d);
    },
    dnsTest(d) {
      const o = $("#dns-test-out");
      if (o) o.innerHTML = d.ok ? `<span class="ok">✓</span> ${esc(d.host)} → ${d.ips.map(esc).join(", ")} <span class="muted">(${d.ms} ms via ${esc(d.provider)})</span>`
        : `<span class="bad">✕ ${esc(d.error)}</span>`;
    },
  };

  // Source: (re)load when the section is opened for a different page
  const _show = show;
  show = function (sec, notify) {
    _show(sec, notify);
    if (sec === "source") {
      const url = D.site && D.site.url;
      if (!D.sourceHtml || (url && D.sourceHtml.url !== url)) V.source.load();
    }
  };
  // keep V.* referencing the wrapped show for rail clicks
  $("#rail").onclick = null;

  /* ========================================================== connect */
  new QWebChannel(qt.webChannelTransport, (channel) => {
    prism = channel.objects.prism;
    prism.push.connect((topic, json) => {
      let d;
      try { d = JSON.parse(json); } catch (e) { return; }
      if (ON[topic]) ON[topic](d);
    });
    prism.ready();
  });
})();
