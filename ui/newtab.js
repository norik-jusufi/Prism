/* PRISM new-tab dashboard. Searches go to SearXNG (the instance Python says is
   answering: your own, or the first public one that isn't busy). Python pushes
   browser stats through window.prismStats() (only when they changed, at most
   once a second). Parts are redrawn only when their data did. */
(function () {
  "use strict";

  // Until Python's first push: the first public instance (see urls.py SEARXNG_INSTANCES).
  let engine = { instance: "https://searx.be", flags: { categories: "general", language: "auto", safesearch: "0" } };
  const $ = (id) => document.getElementById(id);
  const input = $("q");
  const fmt = (n) => Number(n).toLocaleString();
  const pad = (n) => String(n).padStart(2, "0");
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ------------------------------------------------------------- search */
  function looksLikeUrl(t) {
    return /^[a-z][\w+.-]*:\/\//i.test(t) ||
      (!/\s/.test(t) && /^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?(\/.*)?$/i.test(t));
  }

  $("search").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    if (looksLikeUrl(q)) {
      location.href = /^[a-z][\w+.-]*:\/\//i.test(q) ? q : "http://" + q;
      return;
    }
    location.href = engine.instance.replace(/\/$/, "") + "/search?" + new URLSearchParams({ q, ...engine.flags }).toString();
  });

  document.addEventListener("keydown", (e) => {
    const inField = document.activeElement === input;
    if ((e.ctrlKey && e.key.toLowerCase() === "k") || (e.key === "/" && !inField)) {
      e.preventDefault();
      window.focusSearch();
    }
    if (e.key === "Escape" && inField) input.blur();
  });

  window.focusSearch = () => { input.focus(); input.select(); };

  /* -------------------------------------------------------------- tiles */
  const last = {};
  function setNum(id, text) {
    const el = $(id);
    if (el.textContent === text) return;
    el.textContent = text;
    if (last[id] !== undefined) {           // flash on change, not on first paint
      el.classList.remove("tick"); void el.offsetWidth; el.classList.add("tick");
    }
    last[id] = text;
  }

  /* ---------------------------------------------------------- bar chart */
  let timeline = [];
  const bars = $("bars"), yaxis = $("yaxis"), tip = $("tip"), chart = $("chart");

  function niceMax(v) {
    if (v <= 4) return 4;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  function drawChart(tl) {
    timeline = tl;
    const max = niceMax(Math.max(0, ...tl.map((b) => b.req)));
    const ticks = [0, max / 2, max];
    yaxis.innerHTML = ticks.map((t) =>
      `<span style="top:${100 - (t / max) * 100}%">${fmt(Math.round(t))}</span>`).join("");

    let html = ticks.slice(1).map((t) =>
      `<i class="grid" style="top:${100 - (t / max) * 100}%"></i>`).join("");
    html += tl.map((b, i) => {
      const ok = Math.max(0, b.req - b.blk);
      const hBlk = (b.blk / max) * 100, hOk = (ok / max) * 100;
      return `<div class="col" data-i="${i}">` +
        (ok ? `<div class="seg ok" style="height:${hOk}%"></div>` : "") +
        (b.blk ? `<div class="seg blk" style="height:${hBlk}%"></div>` : "") +
        `</div>`;
    }).join("");
    if (!tl.some((b) => b.req)) {
      html += `<div class="empty">no traffic yet<br>// browse something and watch it fill in</div>`;
    }
    bars.innerHTML = html;
    if (hoverIndex !== null) showTip(hoverIndex);
  }

  // tooltip
  let hoverIndex = null;
  bars.addEventListener("mousemove", (e) => {
    const col = e.target.closest(".col");
    if (!col) return hideTip();
    hoverIndex = +col.dataset.i;
    showTip(hoverIndex, e);
  });
  bars.addEventListener("mouseleave", hideTip);
  function hideTip() { hoverIndex = null; tip.hidden = true; }

  function showTip(i) {
    const b = timeline[i];
    const col = bars.querySelector(`.col[data-i="${i}"]`);
    if (!b || !col) return;
    const d = new Date(b.t);
    const rate = b.req ? Math.round((b.blk / b.req) * 100) : 0;
    tip.innerHTML =
      `<div class="t">${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())} · 15 s</div>` +
      `<div><i style="background:var(--green)"></i>blocked <b>${fmt(b.blk)}</b> (${rate}%)</div>` +
      `<div><i style="background:var(--ok)"></i>allowed <b>${fmt(b.req - b.blk)}</b></div>`;
    tip.hidden = false;
    const cr = chart.getBoundingClientRect(), r = col.getBoundingClientRect();
    let x = r.left - cr.left + r.width / 2 - tip.offsetWidth / 2;
    x = Math.max(0, Math.min(cr.width - tip.offsetWidth, x));
    tip.style.left = x + "px";
    tip.style.top = "-6px";
  }

  /* ---------------------------------------------------------- top list */
  function drawTop(top) {
    const el = $("toplist");
    if (!top.length) {
      el.innerHTML = `<li class="empty">nothing blocked yet</li>`;
      return;
    }
    const max = top[0][1];
    el.innerHTML = top.map(([d, n]) =>
      `<li title="${esc(d)}: ${fmt(n)} blocked requests">
         <span class="d">${esc(d)}</span><span class="n">${fmt(n)}</span>
         <span class="track"><span class="fill" style="width:${(n / max) * 100}%;display:block"></span></span>
       </li>`).join("");
  }

  /* ------------------------------------------------------------ uptime */
  let started = Date.now();
  function tickUptime() {
    const s = Math.max(0, Math.floor((Date.now() - started) / 1000));
    $("k-uptime").textContent = `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
  }
  setInterval(tickUptime, 1000);

  /* ------------------------------------------------- called from Python */
  window.prismStats = (s) => {
    started = s.started;
    tickUptime();

    setNum("t-blocked", fmt(s.blocked));
    setNum("t-requests", fmt(s.requests));
    const since = new Date(s.since);
    const sinceText = `since ${since.getFullYear()}-${pad(since.getMonth() + 1)}-${pad(since.getDate())}`;
    $("t-requests-sub").textContent = `network calls ${sinceText}`;
    $("k-since").textContent = `// ${sinceText}`;
    const rate = s.requests ? (s.blocked / s.requests) * 100 : 0;
    setNum("t-rate", (rate >= 10 || rate === 0 ? Math.round(rate) : rate.toFixed(1)) + "%");
    $("t-rate-sub").textContent = `${fmt(s.blocked)} of ${fmt(s.requests)} requests`;
    setNum("t-stripped", fmt(s.stripped));
    setNum("t-cookies", fmt(s.cookies));
    setNum("t-perms", fmt(s.perms));
    $("t-blocked-sub").textContent = s.top.length
      ? `top: ${s.top[0][0]}` : "ads & trackers";

    $("k-pages").textContent = fmt(s.pages);
    $("k-sites").textContent = fmt(s.sites);
    $("k-searches").textContent = fmt(s.searches);
    $("k-https").textContent = s.pages ? Math.round((s.httpsPages / s.pages) * 100) + "%" : "-";
    $("k-tabs").textContent = fmt(s.tabs);
    $("k-exc").textContent = fmt(s.shieldOff);
    $("k-rules").textContent = fmt(s.rules);
    const e = s.engine;
    engine = e;
    const eng = $("f-engine");
    eng.textContent = `${e.name} · ${e.host}${e.own ? " (yours)" : ""}` +
      (e.busy ? ` · ${e.busy}/${e.count} busy` : "");
    eng.classList.toggle("warn", e.busy > 0);
    $("k-fallbacks").textContent = fmt(s.fallbacks);
    $("f-sources").textContent = s.sources.length ? s.sources.join(" · ") : "none";
    drawUpdates(s.updates, s.edition);

    const tlKey = s.timeline.map((b) => b.req + "/" + b.blk).join();
    if (tlKey !== drawn.timeline) { drawn.timeline = tlKey; drawChart(s.timeline); }
    const topKey = JSON.stringify(s.top);
    if (topKey !== drawn.top) { drawn.top = topKey; drawTop(s.top); }
  };
  const drawn = { timeline: null, top: null };

  /* ------------------------------------------ updates (updates.py) */
  let updatesKey = null;
  function drawUpdates(u, edition) {
    if (!u) return;
    const key = JSON.stringify([u, edition]);
    if (key === updatesKey) return;
    updatesKey = key;
    const e = u.engine || {};
    $("f-version").textContent = `PRISM ${u.version}` + (edition === "partner" ? " · partner edition" : "");
    $("f-chromium").textContent = e.chromium
      ? `Chromium ${e.chromium.split(".")[0]}` + (e.patch ? ` · security patches to ${e.patch}` : "") : "-";
    const box = $("notice");
    box.hidden = !u.notes.length;
    box.innerHTML = u.notes.map((n) => `<p><b>${n.kind === "engine" ? "security update" : "update"}</b> ${esc(n.text)}</p>`).join("")
      + installRow(u.install);
  }

  // One-click update (installed Windows copies): the link is handled by PRISM
  // itself (tabs.py), it never leaves the browser.
  function installRow(i) {
    if (!i || !i.available) return "";
    if (i.status === "downloading")
      return `<div class="upd"><span>downloading ${i.progress}%</span><span class="bar"><i style="width:${i.progress}%"></i></span></div>`;
    if (i.status === "starting")
      return `<div class="upd"><span>installing… PRISM restarts in a moment</span></div>`;
    return `<div class="upd"><a href="https://prism.invalid/update">${i.status === "error" ? "Try again" : "Install update"}</a>`
      + (i.status === "error" ? `<span class="err">${esc(i.error)}</span>` : "") + `</div>`;
  }

  input.focus();
})();
