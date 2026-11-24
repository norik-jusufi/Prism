/* PRISM browser chrome logic. Talks to Python (prism.py → Bridge) over QWebChannel. */
(function () {
  "use strict";

  const $ = (s) => document.querySelector(s);
  let bridge = null;
  let state = null;
  let lastTotal = 0;
  let editing = false;          // user is typing in the address bar
  let findWasOpen = false;

  const els = {
    tabs: $("#tabs"), addr: $("#addr"), form: $("#addr-form"), display: $("#addr-display"),
    field: $(".field"), lock: $("#lock"), progress: $("#progress"), zoom: $("#zoom"),
    back: $("#back"), forward: $("#forward"), reload: $("#reload"), home: $("#home"),
    newtab: $("#newtab"), shield: $("#shield"), blocked: $("#blocked"),
    purge: $("#purge"), devtools: $("#devtools"), toast: $("#toast"),
    findbar: $("#findbar"), find: $("#find"), findCount: $("#find-count"),
    ctr: $("#ctr"), trust: $("#trust"), jsoff: $("#jsoff"), dns: $("#dns"),
    split: $("#t-split"), resp: $("#t-resp"), insp: $("#t-insp"), term: $("#t-term"), panel: $("#t-panel"),
    permbar: $("#permbar"), devbar: $("#devbar"), presets: $("#presets"), dl: $("#dl"), tm: $("#tm"),
    devW: $("#dev-w"), devH: $("#dev-h"), devScale: $("#dev-scale"),
  };
  let promptId = null;

  const ICONS = {
    lock: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    open: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/></svg>',
    x:    '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  };

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ------------------------------------------------------------ render */
  function render(s) {
    state = s;
    renderTabs(s.tabs);

    els.back.disabled = !s.canBack;
    els.forward.disabled = !s.canForward;
    els.reload.classList.toggle("loading", s.loading);
    els.reload.title = s.loading ? "Stop (Esc)" : "Reload (Ctrl+R)";

    // address
    if (!editing) els.addr.value = s.url;
    renderDisplay(s);
    if (s.newtab || !s.url) {
      els.lock.innerHTML = "";
    } else if (s.secure) {
      els.lock.innerHTML = ICONS.lock; els.lock.className = "lock"; els.lock.title = "Encrypted connection (HTTPS)";
    } else if (s.scheme === "http") {
      els.lock.innerHTML = ICONS.open; els.lock.className = "lock insecure"; els.lock.title = "Not encrypted (HTTP)";
    } else {
      els.lock.innerHTML = "";
    }

    els.progress.classList.toggle("on", s.loading);
    els.progress.firstElementChild.style.width = (s.loading ? Math.max(8, s.progress) : 100) + "%";

    els.zoom.hidden = s.zoom === 100;
    els.zoom.textContent = s.zoom + "%";

    // shield
    els.blocked.textContent = s.blocked.toLocaleString();
    els.shield.classList.toggle("off", !s.shieldOn);
    els.shield.disabled = s.newtab;
    els.shield.title = s.newtab
      ? `${s.total.toLocaleString()} ads & trackers blocked in total · ${s.rules.toLocaleString()} rules loaded`
      : s.shieldOn
        ? `${s.blocked} ads & trackers blocked on ${s.host} · ${s.total.toLocaleString()} in total.\nClick to turn the shield OFF for this site.`
        : `Shield is OFF for ${s.host}. Click to turn it back on.`;
    if (s.newtab) els.blocked.textContent = s.total.toLocaleString();
    if (s.total > lastTotal) {
      els.shield.classList.remove("bump"); void els.shield.offsetWidth; els.shield.classList.add("bump");
    }
    lastTotal = s.total;

    // telemetry readout
    $("#r-req").textContent = compact(s.requests);
    $("#r-blk").textContent = compact(s.total);

    // container chip (hidden for the default container)
    const c = s.container;
    const showCtr = c && c.id !== "default";
    els.ctr.hidden = !showCtr;
    if (showCtr) {
      els.ctr.textContent = c.kind === "sandbox" ? "sandbox" : c.name;
      els.ctr.style.setProperty("--cc", c.color);
    }
    // trust score
    els.trust.hidden = !s.trust;
    if (s.trust) {
      els.trust.textContent = s.trust.score;
      els.trust.className = "trust g-" + s.trust.grade;
      els.trust.title = `Trust score ${s.trust.score}/100 (grade ${s.trust.grade}). Click for the full report.`;
    }
    els.jsoff.hidden = !s.jsOff;
    els.jsoff.textContent = c && c.kind === "sandbox" ? "JS off · allow" : "JS off";
    els.dns.hidden = s.dns === "off";
    els.dns.title = s.dns === "strict" ? "Encrypted DNS (strict): no plain-text lookups" : "Encrypted DNS is on";

    // tool toggles
    els.split.classList.toggle("on", s.panes > 1);
    els.resp.classList.toggle("on", !!s.device);
    els.insp.classList.toggle("on", s.inspector);
    els.panel.classList.toggle("on", s.panel && s.panelSection !== "terminal");
    els.term.classList.toggle("on", s.panel && s.panelSection === "terminal");
    $("#devtools").classList.toggle("on", s.devtools);
    els.tm.classList.toggle("on", !!s.timeMachine);
    renderDownloads(s.downloads);

    // permission prompt
    els.permbar.hidden = !s.prompt;
    if (s.prompt && s.prompt.id !== promptId) {
      $("#perm-site").textContent = s.prompt.site;
      $("#perm-what").textContent = s.prompt.label.toLowerCase();
      $("#perm-remember").checked = false;
    }
    promptId = s.prompt ? s.prompt.id : null;

    // responsive preview
    els.devbar.hidden = !s.device;
    if (s.device) {
      if (!els.presets.childElementCount) {
        els.presets.innerHTML = s.devices.map((d) =>
          `<button data-w="${d.w}" data-h="${d.h}" data-name="${esc(d.name)}" title="${d.w} × ${d.h}">${esc(d.name)}</button>`).join("");
      }
      for (const b of els.presets.children) {
        b.classList.toggle("on", (+b.dataset.w === s.device.w && +b.dataset.h === s.device.h) ||
                                 (+b.dataset.w === s.device.h && +b.dataset.h === s.device.w));
      }
      if (document.activeElement !== els.devW) els.devW.value = s.device.w;
      if (document.activeElement !== els.devH) els.devH.value = s.device.h;
      els.devScale.textContent = s.device.scale ? `shown at ${Math.round(s.device.scale * 100)}%` : "";
    }

    // find
    els.findbar.hidden = !s.find.open;
    if (s.find.open) {
      const has = s.find.text.length > 0;
      els.findCount.textContent = has ? (s.find.matches ? `${s.find.active}/${s.find.matches}` : "no matches") : "";
      els.find.classList.toggle("none", has && s.find.matches === 0);
      if (!findWasOpen) { els.find.value = s.find.text; focusFind(); }
    }
    findWasOpen = s.find.open;
  }

  function renderDownloads(d) {
    if (!d) return;
    const b = els.dl;
    const active = d.active > 0;
    b.classList.toggle("active", active);
    b.classList.toggle("indet", active && d.progress < 0);
    b.classList.toggle("just-done", !active && d.justDone);
    b.classList.toggle("failed", !active && !d.justDone && d.failed);
    b.style.setProperty("--p", active && d.progress >= 0 ? (d.progress * 100).toFixed(1) : (active ? 25 : 0));
    const badge = b.querySelector(".badge");
    badge.hidden = d.active < 2;
    badge.textContent = d.active;
    b.title = active
      ? `Downloading ${d.active} file${d.active > 1 ? "s" : ""}` +
        (d.progress >= 0 ? ` · ${Math.round(d.progress * 100)}%` : "") +
        (d.speed > 0 ? ` · ${humanSpeed(d.speed)}` : "") + "\nClick for details"
      : d.count ? `Downloads (${d.count} this session)` : "Downloads";
  }

  function humanSpeed(n) {
    const u = ["B/s", "KB/s", "MB/s", "GB/s"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1) : Math.round(n)) + " " + u[i];
  }

  function renderDisplay(s) {
    const show = !editing && s.url && !s.newtab;
    els.field.classList.toggle("show-display", !!show);
    if (!show) return;
    // dim everything except the host, so phishing look-alikes stand out
    const u = s.url;
    const i = s.host ? u.indexOf(s.host) : -1;
    els.display.innerHTML = i < 0 ? esc(u)
      : esc(u.slice(0, i)) + "<b>" + esc(s.host) + "</b>" + esc(u.slice(i + s.host.length));
  }

  function renderTabs(tabs) {
    const html = tabs.map((t) => {
      const fav = t.loading ? '<i class="spin"></i>'
        : t.icon ? `<img src="${t.icon}" alt="">`
        : '<i class="ph"></i>';
      const c = t.container;
      const cc = c && c.id !== "default" ? ` data-cc="${esc(c.id)}" style="--cc:${esc(c.color)}"` : "";
      const label = c && c.id !== "default" ? `<span class="cc">${esc(c.kind === "temp" ? "temp" : c.kind === "sandbox" ? "sandbox" : c.name)}</span>` : "";
      const cls = (t.active ? " active" : "") + (t.shown && !t.active ? " shown" : "") + (t.discarded ? " discarded" : "");
      const tip = esc(t.title) + (c && c.id !== "default" ? ` · ${esc(c.name)}` : "") + (t.discarded ? " · discarded" : "");
      return `<div class="tab${cls}" data-id="${t.id}" role="tab" title="${tip}"${cc}>
        <span class="fav">${fav}</span>
        ${t.asking ? '<i class="ask" title="This tab is asking for a permission"></i>' : ""}
        <span class="title">${esc(t.title)}</span>${label}
        <button class="x" data-close="${t.id}" title="Close tab (Ctrl+W)">${ICONS.x}</button>
      </div>`;
    }).join("");
    if (els.tabs.innerHTML !== html) els.tabs.innerHTML = html;
    els.tabs.classList.toggle("narrow", tabs.length > 8);
  }

  function compact(n) {
    return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? (n / 1e3).toFixed(1) + "k" : String(n);
  }

  const clock = $("#r-clock");
  const pad = (n) => String(n).padStart(2, "0");
  function tick() {
    const d = new Date();
    clock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
  tick(); setInterval(tick, 1000);

  /* ------------------------------------------------------------ events */
  els.tabs.addEventListener("mousedown", (e) => {
    const tab = e.target.closest(".tab");
    if (!tab || !bridge) return;
    const id = +tab.dataset.id;
    if (e.button === 1) { e.preventDefault(); bridge.closeTab(id); return; }   // middle click
    if (e.button !== 0) return;
    // Act on mousedown: the strip is re-rendered while pages load, so a
    // click could otherwise land on a replaced element.
    if (e.target.closest(".x")) bridge.closeTab(id);
    else bridge.switchTab(id);
  });
  els.tabs.addEventListener("dblclick", (e) => {
    if (!e.target.closest(".tab") && bridge) bridge.newTab();
  });

  els.newtab.onclick = () => bridge && bridge.newTab();
  els.newtab.addEventListener("contextmenu", (e) => { e.preventDefault(); bridge && bridge.newTabMenu(); });
  $("#newtab-menu").onclick = () => bridge && bridge.newTabMenu();
  els.tabs.addEventListener("contextmenu", (e) => {
    const tab = e.target.closest(".tab");
    e.preventDefault();
    if (tab && bridge) bridge.tabMenu(+tab.dataset.id);
    else if (bridge) bridge.newTabMenu();
  });
  els.split.onclick = () => bridge.split();
  els.resp.onclick = () => bridge.responsive();
  els.insp.onclick = () => bridge.inspector();
  els.term.onclick = () => bridge.panel("terminal");
  els.panel.onclick = () => bridge.panel("");
  els.trust.onclick = () => bridge.panel("site");
  els.ctr.onclick = () => bridge.containerMenu();
  els.jsoff.onclick = () => (state && state.container.kind === "sandbox" ? bridge.sandboxJs() : bridge.panel("site"));
  $("#perm-allow").onclick = () => promptId && bridge.answerPermission(promptId, true, $("#perm-remember").checked);
  $("#perm-block").onclick = () => promptId && bridge.answerPermission(promptId, false, $("#perm-remember").checked);
  $("#perm-center").onclick = () => bridge.panel("permissions");
  els.presets.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) bridge.setDevice(b.dataset.name, +b.dataset.w, +b.dataset.h);
  });
  const applyDims = () => {
    const w = +els.devW.value, h = +els.devH.value;
    if (w >= 200 && h >= 200) bridge.setDevice("Custom", w, h);
  };
  for (const inp of [els.devW, els.devH]) {
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { applyDims(); inp.blur(); } });
    inp.addEventListener("change", applyDims);
  }
  $("#dev-rotate").onclick = () => bridge.rotateDevice();
  $("#dev-close").onclick = () => bridge.responsive();
  els.back.onclick = () => bridge.back();
  els.forward.onclick = () => bridge.forward();
  els.reload.onclick = () => (state && state.loading ? bridge.stop() : bridge.reload());
  els.home.onclick = () => bridge.home();
  els.devtools.onclick = () => bridge.devtools();
  els.shield.onclick = () => bridge.toggleShield();
  els.tm.onclick = () => bridge.timeMachine();
  els.dl.onclick = () => {
    const r = els.dl.getBoundingClientRect();
    bridge.downloadsMenu(Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height));
  };

  // purge needs a second click within 3s
  let purgeTimer = null;
  els.purge.onclick = () => {
    const label = els.purge.querySelector(".label");
    if (els.purge.classList.contains("confirm")) {
      clearTimeout(purgeTimer);
      els.purge.classList.remove("confirm");
      label.textContent = "purge";
      bridge.purge();
      return;
    }
    els.purge.classList.add("confirm");
    label.textContent = "confirm?";
    purgeTimer = setTimeout(() => {
      els.purge.classList.remove("confirm");
      label.textContent = "purge";
    }, 3000);
  };

  // address bar
  els.addr.addEventListener("focus", () => {
    editing = true;
    els.form.classList.add("focus");
    els.field.classList.remove("show-display");
    setTimeout(() => els.addr.select(), 0);
  });
  els.addr.addEventListener("blur", () => {
    editing = false;
    els.form.classList.remove("focus");
    if (state) { els.addr.value = state.url; renderDisplay(state); }
  });
  els.addr.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      els.addr.value = state ? state.url : "";
      els.addr.blur();
      bridge && bridge.focusPage();
    }
  });
  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = els.addr.value.trim();
    if (!v || !bridge) return;
    editing = false;
    els.addr.blur();
    bridge.navigate(v);
  });
  els.form.addEventListener("mousedown", (e) => {
    if (e.target !== els.addr && !e.target.closest("button")) { e.preventDefault(); els.addr.focus(); }
  });

  // find bar
  els.find.addEventListener("input", () => bridge.find(els.find.value, false));
  els.find.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); bridge.find(els.find.value, e.shiftKey); }
    if (e.key === "Escape") bridge.findClose();
  });
  $("#find-next").onclick = () => bridge.find(els.find.value, false);
  $("#find-prev").onclick = () => bridge.find(els.find.value, true);
  $("#find-close").onclick = () => bridge.findClose();

  /* ---------------------------------------------- called from Python */
  window.focusAddress = () => { els.addr.focus(); els.addr.select(); };
  window.openFind = () => focusFind();
  function focusFind() {
    els.findbar.hidden = false;
    setTimeout(() => { els.find.focus(); els.find.select(); }, 0);
  }

  let toastTimer = null;
  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("show"), 3500);
  }

  /* --------------------------------------------------------- connect */
  function reportHeight() {
    if (bridge) bridge.setChromeHeight(Math.ceil($("#chrome").getBoundingClientRect().height));
  }
  new ResizeObserver(reportHeight).observe($("#chrome"));

  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    bridge.stateChanged.connect((json) => render(JSON.parse(json)));
    bridge.toast.connect(showToast);
    bridge.ready();
    reportHeight();
  });
})();
