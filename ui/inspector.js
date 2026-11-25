/* PRISM design inspector. Injected into the page's isolated JS world (the page
   can't see or touch it). Hover = inspect, click = pin, Alt = measure distance
   from the pinned element, ↑ = select parent, C = copy CSS, Esc = exit. */
(function () {
  "use strict";
  if (window.__prismInspect) return;

  let on = false, host = null, root = null, hovered = null, pinned = null, alt = false;
  const PROPS = ["display", "position", "box-sizing", "width", "height", "margin", "padding", "border",
    "border-radius", "color", "background-color", "background-image", "font-family", "font-size",
    "font-weight", "line-height", "letter-spacing", "text-align", "text-transform", "opacity",
    "box-shadow", "z-index", "overflow", "gap", "flex-direction", "justify-content", "align-items",
    "grid-template-columns", "transition", "cursor"];

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .layer { position: fixed; inset: 0; pointer-events: none; z-index: 2147483647;
             font: 11px/1.45 "Cascadia Code", Consolas, monospace; }
    .box { position: fixed; pointer-events: none; }
    .m { background: rgba(245, 200, 76, .22); }
    .b { background: rgba(255, 154, 92, .30); }
    .p { background: rgba(54, 245, 155, .22); }
    .c { background: rgba(79, 216, 232, .26); outline: 1px solid rgba(79, 216, 232, .9); }
    .pin { outline: 2px solid #36f59b; outline-offset: -1px; }
    .card { position: fixed; pointer-events: auto; width: 300px; max-height: 70vh; overflow: auto;
            background: #040a07; color: #e8f5ec; border: 1px solid #1f5537;
            box-shadow: 0 8px 28px rgba(0,0,0,.55); padding: 10px 12px; }
    .card h4 { margin: 0 0 6px; font: 600 12px/1.3 "Cascadia Code", Consolas, monospace; color: #36f59b;
               word-break: break-all; }
    .card h4 small { color: #a9c9b5; font-weight: 400; }
    .row { display: grid; grid-template-columns: 92px 1fr; gap: 0 8px; padding: 2px 0;
           border-bottom: 1px dashed #10261a; }
    .row:last-child { border-bottom: 0; }
    .k { color: #5f8270; }
    .v { color: #e8f5ec; word-break: break-word; }
    .sw { display: inline-block; width: 10px; height: 10px; margin-right: 6px; vertical-align: -1px;
          border: 1px solid #1f5537; }
    .sec { margin: 8px 0 4px; color: #5f8270; text-transform: uppercase; letter-spacing: .12em; font-size: 9.5px; }
    .bm { display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; gap: 2px; font-size: 10px; }
    .bm div { padding: 3px 0; }
    .bm .lm { background: rgba(245, 200, 76, .18); } .bm .lb { background: rgba(255, 154, 92, .22); }
    .bm .lp { background: rgba(54, 245, 155, .18); } .bm .lc { background: rgba(79, 216, 232, .22); }
    .ok { color: #36f59b; } .warn { color: #ffc65c; } .bad { color: #ff5f6d; }
    .hint { margin-top: 8px; color: #5f8270; font-size: 10px; }
    .btns { display: flex; gap: 6px; margin-top: 8px; }
    button { all: unset; cursor: pointer; padding: 3px 8px; border: 1px solid #1f5537; color: #a9c9b5;
             font: 11px "Cascadia Code", Consolas, monospace; }
    button:hover { border-color: #36f59b; color: #36f59b; }
    .tag { position: fixed; padding: 1px 6px; background: #36f59b; color: #040a07; font-weight: 700;
           white-space: nowrap; }
    .dist { position: fixed; background: #ff5f6d; }
    .dlabel { position: fixed; padding: 0 4px; background: #ff5f6d; color: #fff; font-weight: 700;
              transform: translate(-50%, -50%); white-space: nowrap; }
    .badge { position: fixed; top: 8px; left: 50%; transform: translateX(-50%); pointer-events: none;
             padding: 3px 10px; background: #040a07; border: 1px solid #36f59b; color: #36f59b; }
  `;

  function ensure() {
    if (host && host.isConnected) return;
    host = document.createElement("prism-inspector");
    root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `<style>${CSS}</style><div class="layer"></div>`;
    (document.documentElement || document.body).appendChild(host);
  }
  const layer = () => root.querySelector(".layer");

  /* ---------------------------------------------------------- utilities */
  const px = (v) => parseFloat(v) || 0;
  function hex(c) {
    const m = String(c).match(/rgba?\(([^)]+)\)/);
    if (!m) return c;
    const [r, g, b, a = 1] = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    const h = "#" + [r, g, b].map((n) => Math.round(n).toString(16).padStart(2, "0")).join("");
    return a < 1 ? `${h} / ${Math.round(a * 100)}%` : h;
  }
  function rgb(c) {
    const m = String(c).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] };
  }
  function lum({ r, g, b }) {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  }
  function effectiveBg(el) {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const c = rgb(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0.05) return c;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  }
  function contrast(el, cs) {
    const fg = rgb(cs.color);
    if (!fg) return null;
    const l1 = lum(fg), l2 = lum(effectiveBg(el));
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  }
  function label(el) {
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).filter(Boolean) : [];
    if (cls.length) s += "." + cls.slice(0, 3).join(".") + (cls.length > 3 ? "…" : "");
    return s;
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function four(cs, prop) {
    const v = ["top", "right", "bottom", "left"].map((s) => px(cs[`${prop}-${s}${prop === "border" ? "-width" : ""}`] || cs.getPropertyValue(`${prop}-${s}${prop === "border" ? "-width" : ""}`)));
    return v.every((x) => x === v[0]) ? `${v[0]}` : v.join(" ");
  }

  /* -------------------------------------------------------------- render */
  function box(cls, x, y, w, h) {
    if (w <= 0 || h <= 0) return "";
    return `<div class="box ${cls}" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px"></div>`;
  }

  function boxModel(el, cls) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    const m = { t: px(cs.marginTop), r: px(cs.marginRight), b: px(cs.marginBottom), l: px(cs.marginLeft) };
    const bd = { t: px(cs.borderTopWidth), r: px(cs.borderRightWidth), b: px(cs.borderBottomWidth), l: px(cs.borderLeftWidth) };
    const p = { t: px(cs.paddingTop), r: px(cs.paddingRight), b: px(cs.paddingBottom), l: px(cs.paddingLeft) };
    let h = "";
    // margin (4 strips)
    h += box("m", r.left - m.l, r.top - m.t, r.width + m.l + m.r, m.t);
    h += box("m", r.left - m.l, r.bottom, r.width + m.l + m.r, m.b);
    h += box("m", r.left - m.l, r.top, m.l, r.height);
    h += box("m", r.right, r.top, m.r, r.height);
    // border
    h += box("b", r.left, r.top, r.width, bd.t);
    h += box("b", r.left, r.bottom - bd.b, r.width, bd.b);
    h += box("b", r.left, r.top + bd.t, bd.l, r.height - bd.t - bd.b);
    h += box("b", r.right - bd.r, r.top + bd.t, bd.r, r.height - bd.t - bd.b);
    // padding
    const ix = r.left + bd.l, iy = r.top + bd.t, iw = r.width - bd.l - bd.r, ih = r.height - bd.t - bd.b;
    h += box("p", ix, iy, iw, p.t);
    h += box("p", ix, iy + ih - p.b, iw, p.b);
    h += box("p", ix, iy + p.t, p.l, ih - p.t - p.b);
    h += box("p", ix + iw - p.r, iy + p.t, p.r, ih - p.t - p.b);
    // content
    h += box("c " + (cls || ""), ix + p.l, iy + p.t, iw - p.l - p.r, ih - p.t - p.b);
    return { html: h, rect: r, m, bd, p };
  }

  function distances(a, b) {
    const A = a.getBoundingClientRect(), B = b.getBoundingClientRect();
    let h = "";
    const line = (x, y, w, hgt, val, lx, ly) => {
      if (val <= 0) return;
      h += `<div class="dist" style="left:${x}px;top:${y}px;width:${Math.max(1, w)}px;height:${Math.max(1, hgt)}px"></div>`;
      h += `<div class="dlabel" style="left:${lx}px;top:${ly}px">${Math.round(val)}</div>`;
    };
    const cx = (Math.max(A.left, B.left) + Math.min(A.right, B.right)) / 2;
    const cy = (Math.max(A.top, B.top) + Math.min(A.bottom, B.bottom)) / 2;
    if (B.top >= A.bottom) line(cx, A.bottom, 1, B.top - A.bottom, B.top - A.bottom, cx, (A.bottom + B.top) / 2);
    else if (A.top >= B.bottom) line(cx, B.bottom, 1, A.top - B.bottom, A.top - B.bottom, cx, (B.bottom + A.top) / 2);
    else { // overlapping vertically: inner gaps
      line(cx, Math.min(A.top, B.top), 1, Math.abs(A.top - B.top), Math.abs(A.top - B.top), cx, (A.top + B.top) / 2);
      line(cx, Math.min(A.bottom, B.bottom), 1, Math.abs(A.bottom - B.bottom), Math.abs(A.bottom - B.bottom), cx, (A.bottom + B.bottom) / 2);
    }
    if (B.left >= A.right) line(A.right, cy, B.left - A.right, 1, B.left - A.right, (A.right + B.left) / 2, cy);
    else if (A.left >= B.right) line(B.right, cy, A.left - B.right, 1, A.left - B.right, (B.right + A.left) / 2, cy);
    else {
      line(Math.min(A.left, B.left), cy, Math.abs(A.left - B.left), 1, Math.abs(A.left - B.left), (A.left + B.left) / 2, cy);
      line(Math.min(A.right, B.right), cy, Math.abs(A.right - B.right), 1, Math.abs(A.right - B.right), (A.right + B.right) / 2, cy);
    }
    return h;
  }

  function card(el, pinnedMode) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    const ratio = contrast(el, cs);
    const hasText = Array.prototype.some.call(el.childNodes, (n) => n.nodeType === 3 && n.textContent.trim());
    const grade = ratio == null ? "" : ratio >= 7 ? "AAA" : ratio >= 4.5 ? "AA" : ratio >= 3 ? "AA large" : "fail";
    const gcls = ratio == null ? "" : ratio >= 4.5 ? "ok" : ratio >= 3 ? "warn" : "bad";
    const row = (k, v) => `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`;
    const color = (c) => `<span class="sw" style="background:${esc(c)}"></span>${esc(hex(c))}`;
    const font = cs.fontFamily.split(",")[0].replace(/["']/g, "");
    let h = `<h4>${esc(label(el))} <small>${Math.round(r.width * 10) / 10} × ${Math.round(r.height * 10) / 10}</small></h4>`;
    h += `<div class="sec">Typography</div>`;
    h += row("font", `${esc(font)} <span class="k">${esc(cs.fontWeight)}</span>`);
    h += row("size / line", `${esc(cs.fontSize)} / ${esc(cs.lineHeight)}`);
    if (cs.letterSpacing !== "normal") h += row("tracking", esc(cs.letterSpacing));
    h += `<div class="sec">Color</div>`;
    h += row("text", color(cs.color));
    h += row("background", color(cs.backgroundColor) + (cs.backgroundImage !== "none" ? ' <span class="k">+ image/gradient</span>' : ""));
    if (hasText && ratio != null) h += row("contrast", `<span class="${gcls}">${ratio.toFixed(2)} : 1 · ${grade}</span>`);
    if (px(cs.borderTopWidth)) h += row("border", `${esc(cs.borderTopWidth)} ${esc(cs.borderTopStyle)} ${color(cs.borderTopColor)}`);
    h += `<div class="sec">Spacing</div>`;
    h += `<div class="bm"><div class="lm">margin<br>${four(cs, "margin")}</div><div class="lb">border<br>${four(cs, "border")}</div><div class="lp">padding<br>${four(cs, "padding")}</div></div>`;
    h += `<div class="sec">Layout</div>`;
    h += row("display", esc(cs.display) + (cs.position !== "static" ? ` · ${esc(cs.position)}` : ""));
    if (/flex|grid/.test(cs.display)) {
      if (cs.display.includes("flex")) h += row("flex", `${esc(cs.flexDirection)} · ${esc(cs.justifyContent)} · ${esc(cs.alignItems)}`);
      if (cs.display.includes("grid")) h += row("columns", esc(cs.gridTemplateColumns).slice(0, 80));
      if (cs.gap && cs.gap !== "normal") h += row("gap", esc(cs.gap));
    }
    if (cs.borderRadius !== "0px") h += row("radius", esc(cs.borderRadius));
    if (cs.boxShadow !== "none") h += row("shadow", esc(cs.boxShadow).slice(0, 90));
    if (cs.zIndex !== "auto") h += row("z-index", esc(cs.zIndex));
    if (cs.opacity !== "1") h += row("opacity", esc(cs.opacity));
    if (pinnedMode) {
      h += `<div class="btns"><button data-act="copy">Copy CSS</button><button data-act="parent">Parent ↑</button><button data-act="unpin">Unpin</button></div>`;
      h += `<div class="hint">Hold Alt and hover another element to measure the gap.</div>`;
    } else {
      h += `<div class="hint">Click to pin · ↑ parent · Esc to exit</div>`;
    }
    return h;
  }

  function place(cardEl, rect) {
    const W = innerWidth, H = innerHeight, cw = 300, ch = cardEl.offsetHeight || 300;
    let x = rect.right + 12, y = rect.top;
    if (x + cw > W - 8) x = rect.left - cw - 12;
    if (x < 8) x = Math.min(W - cw - 8, Math.max(8, rect.left));
    if (x < 8) x = 8;
    if (y + ch > H - 8) y = H - ch - 8;
    if (y < 8) y = 8;
    cardEl.style.left = x + "px";
    cardEl.style.top = y + "px";
  }

  function render() {
    if (!on) return;
    ensure();
    const target = pinned || hovered;
    let h = `<div class="badge">design inspector · ${pinned ? "pinned" : "hover"} · Esc to exit</div>`;
    if (pinned) {
      h += boxModel(pinned, "pin").html;
      if (alt && hovered && hovered !== pinned) {
        h += boxModel(hovered).html;
        h += distances(pinned, hovered);
      }
    } else if (hovered) {
      h += boxModel(hovered).html;
    }
    if (target) {
      const r = target.getBoundingClientRect();
      h += `<div class="tag" style="left:${Math.max(0, r.left)}px;top:${Math.max(0, r.top - 18)}px">${esc(label(target))}</div>`;
      h += `<div class="card">${card(target, !!pinned)}</div>`;
    }
    layer().innerHTML = h;
    const c = root.querySelector(".card");
    if (c && target) place(c, target.getBoundingClientRect());
  }

  function cssText(el) {
    const cs = getComputedStyle(el);
    const lines = PROPS.map((p) => [p, cs.getPropertyValue(p)])
      .filter(([p, v]) => v && v !== "none" && v !== "normal" && v !== "auto" && !(p === "opacity" && v === "1")
        && !(p === "z-index" && v === "auto") && v !== "0px" && v !== "rgba(0, 0, 0, 0)")
      .map(([p, v]) => `  ${p}: ${/color/.test(p) ? hex(v).replace(/ \/ (\d+)%/, "") : v};`);
    return `${label(el)} {\n${lines.join("\n")}\n}`;
  }
  function copy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
    root.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    ta.remove();
  }

  /* -------------------------------------------------------------- events */
  const inOverlay = (e) => e.composedPath && e.composedPath().includes(host);
  function onMove(e) {
    if (inOverlay(e)) return;
    alt = e.altKey;
    const el = e.target;
    if (el && el.nodeType === 1 && el !== hovered) { hovered = el; render(); }
    else if (pinned) render();
  }
  function onClick(e) {
    if (inOverlay(e)) {
      const act = e.composedPath()[0].dataset && e.composedPath()[0].dataset.act;
      if (act === "copy" && pinned) copy(cssText(pinned));
      if (act === "parent" && pinned && pinned.parentElement) pinned = pinned.parentElement;
      if (act === "unpin") pinned = null;
      if (act) { e.preventDefault(); e.stopPropagation(); render(); }
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    pinned = pinned === e.target ? null : e.target;
    render();
  }
  function block(e) { if (!inOverlay(e)) { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); } }
  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); stop(); return; }
    if (e.key === "Alt") { alt = e.type === "keydown"; render(); return; }
    if (e.type !== "keydown") return;
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (pinned && pinned.parentElement) pinned = pinned.parentElement;
      else if (hovered && hovered.parentElement) hovered = hovered.parentElement;
      render();
    }
    if ((e.key === "c" || e.key === "C") && pinned && !e.ctrlKey && !e.metaKey) { e.preventDefault(); copy(cssText(pinned)); }
  }
  const onScroll = () => render();

  function start() {
    on = true;
    ensure();
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("click", onClick, true);
    ["mousedown", "mouseup", "pointerdown", "pointerup", "dblclick", "contextmenu"].forEach((t) => document.addEventListener(t, block, true));
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("keyup", onKey, true);
    addEventListener("scroll", onScroll, true);
    addEventListener("resize", onScroll);
    document.documentElement.style.setProperty("cursor", "crosshair", "important");
    render();
  }
  function stop() {
    on = false;
    hovered = pinned = null;
    document.removeEventListener("mousemove", onMove, true);
    document.removeEventListener("click", onClick, true);
    ["mousedown", "mouseup", "pointerdown", "pointerup", "dblclick", "contextmenu"].forEach((t) => document.removeEventListener(t, block, true));
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("keyup", onKey, true);
    removeEventListener("scroll", onScroll, true);
    removeEventListener("resize", onScroll);
    document.documentElement.style.removeProperty("cursor");
    if (host) host.remove();
    host = root = null;
  }

  window.__prismInspect = {
    toggle() { on ? stop() : start(); return on; },
    stop() { stop(); return false; },
    isOn() { return on; },
  };
})();
