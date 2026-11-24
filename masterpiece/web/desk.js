"use strict";
// "Your desktop" on the Curator tab: a live preview of your screens (what is cut off, the whole
// painting with its edges, the label), the layout and label settings beside it, and what comes next.
// Needs shell.js and curator.js (cur, saveSettings, refreshLabel, thumbUrl).

const LABEL_SIZE_DIV = { s: 72, m: 55, l: 40 };       // same as wallpaper.LABEL_SIZES
const CROP_AT = { middle: [0.5, 0.5], bottom: [0.5, 1], top: [0.5, 0] };   // same as wallpaper.CROPS
const SOFT_SCALE = 1.3;                                // same as wallpaper.SOFT_SCALE
const AUTO_BRIGHT = 0.62;                              // same as wallpaper.AUTO_BRIGHT
const DEFAULT_STYLE = { look: "dark", font: "sans", size: "m", text: "full", where: "all" };
const desk = { drag: null, timer: null, live: {} };   // live: focus while dragging, per painting

function labelLines(a, mode) {                         // mirrors wallpaper.label_lines
  const j = (sep, ...xs) => xs.filter(Boolean).join(sep);
  const year = String(a.year || "").trim().slice(0, 24);
  const by = j(", ", a.maker, year);
  if (mode === "title") return [year ? `${a.title} (${year})` : a.title];
  if (mode === "artist") return [j(" — ", a.title, by)];
  if (mode === "two") return [a.title, j(" · ", by, a.museum)];
  return [j(" · ", j(" — ", a.title, by), a.museum)];
}

function labelledScreens(mons, where) {                // mirrors wallpaper.labelled_screens
  if (mons.length < 2 || !["main", "left", "right"].includes(where)) return new Set(mons);
  if (where === "main") return new Set([mons.find((m) => m.primary) || mons[0]]);
  const by = where === "left" ? (a, m) => (m.x < a.x || (m.x === a.x && m.y < a.y) ? m : a)
    : (a, m) => (m.x + m.width > a.x + a.width || (m.x + m.width === a.x + a.width && m.y < a.y) ? m : a);
  return new Set([mons.reduce(by)]);
}

const style = () => ({ ...DEFAULT_STYLE, ...(cur.s.labelStyle || {}) });
const cropMode = () => cur.s.crop || "middle";

// Where a painting lands in a box (w×h): its drawn size and offset, and how much is cut off.
function placePainting(p, w, h) {
  const iw = p.w || w, ih = p.h || h;
  if (cropMode() === "whole") {
    const edges = cur.s.edges || "blur";
    const room = edges === "frame" ? 0.86 : edges === "mat" ? 0.94 : 1;
    const s = Math.min(w / iw, h / ih) * room;
    const dw = iw * s, dh = ih * s;
    return { whole: true, dw, dh, x: (w - dw) / 2, y: (h - dh) / 2, cut: 0, scale: Math.min(w / iw, h / ih) };
  }
  const s = Math.max(w / iw, h / ih), dw = iw * s, dh = ih * s;
  const [cx, cy] = desk.live[p.name] || p.focus || CROP_AT[cropMode()] || CROP_AT.middle;
  return { whole: false, dw, dh, x: -(dw - w) * cx, y: -(dh - h) * cy, cut: 1 - (w * h) / (dw * dh), scale: s, cx, cy };
}

const isSoft = (p, w, h) => (p.w && p.h) ? placePainting(p, w, h).scale > SOFT_SCALE : false;

// ------------------------------------------------------------------ the preview
function deskTargets() {
  const r = cur.rot, mons = r.screens && r.screens.length ? r.screens
    : [{ id: null, x: 0, y: 0, width: 1920, height: 1080, primary: true }];
  const on = r.onScreens || [];
  const x0 = Math.min(...mons.map((m) => m.x)), y0 = Math.min(...mons.map((m) => m.y));
  const W = Math.max(...mons.map((m) => m.x + m.width)) - x0, H = Math.max(...mons.map((m) => m.y + m.height)) - y0;
  const span = on.find((c) => c.key === "span");
  const all = on.find((c) => c.key === "all");
  const targets = span
    ? [{ box: { x: 0, y: 0, w: W, h: H }, p: span, mons }]
    : mons.map((m) => ({ box: { x: m.x - x0, y: m.y - y0, w: m.width, h: m.height },
                         p: on.find((c) => c.key === m.id) || all || null, mons: [m] }));
  return { mons, x0, y0, W, H, targets };
}

function renderDesk() {
  const stage = $("deskStage");
  if (!stage) return;
  const { mons, x0, y0, W, H, targets } = deskTargets();
  const st = style(), withLabel = labelledScreens(mons, st.where);
  // room around the screens for the faded, cut-off parts
  let padL = 0, padR = 0, padT = 0, padB = 0;
  for (const t of targets) {
    if (!t.p) continue;
    const g = placePainting(t.p, t.box.w, t.box.h);
    padL = Math.max(padL, -(t.box.x + g.x)); padT = Math.max(padT, -(t.box.y + g.y));
    padR = Math.max(padR, t.box.x + g.x + g.dw - W); padB = Math.max(padB, t.box.y + g.y + g.dh - H);
  }
  const box = getComputedStyle(stage.parentElement);
  const availW = stage.parentElement.clientWidth - parseFloat(box.paddingLeft) - parseFloat(box.paddingRight), maxH = Math.max(220, Math.min(560, innerHeight - 330));
  const k = Math.min(availW / (W + padL + padR), maxH / (H + padT + padB));
  stage.style.width = `${(W + padL + padR) * k}px`;
  stage.style.height = `${(H + padT + padB) * k}px`;
  const ox = padL * k, oy = padT * k;
  const kids = [];

  targets.forEach((t, ti) => {
    if (!t.p) return;
    const g = placePainting(t.p, t.box.w, t.box.h);
    const left = ox + (t.box.x + g.x) * k, top = oy + (t.box.y + g.y) * k;
    if (!g.whole && g.cut > 0.01) {                     // the faded part that is cut off
      kids.push(el("img", { class: "desk-ghost", src: thumbUrl(t.p.name, true), alt: "",
        style: `left:${left}px;top:${top}px;width:${g.dw * k}px;height:${g.dh * k}px` }));
    }
  });

  mons.forEach((m) => {
    const t = targets.find((tt) => tt.mons.includes(m));
    const gap = mons.length > 1 ? 3 : 0;               // a hair between screens that touch
    const sx = ox + (m.x - x0) * k + gap, sy = oy + (m.y - y0) * k, sw = m.width * k - 2 * gap, sh = m.height * k;
    const win = el("div", { class: "desk-screen", style: `left:${sx}px;top:${sy}px;width:${sw}px;height:${sh}px`,
                            "data-name": t && t.p ? t.p.name : "", "data-w": m.width });
    if (t && t.p) {
      const g = placePainting(t.p, t.box.w, t.box.h);
      const px = (t.box.x + g.x) * k - (m.x - x0) * k - gap, py = (t.box.y + g.y) * k - (m.y - y0) * k;
      if (g.whole) {
        const edges = cur.s.edges || "blur";
        win.classList.add(`edges-${edges}`);
        if (edges === "blur") win.append(el("img", { class: "desk-blur", src: thumbUrl(t.p.name, true), alt: "" }));
        win.append(el("img", { class: `desk-img${edges === "frame" ? " framed" : ""}`, src: thumbUrl(t.p.name, true), alt: t.p.title,
          style: `left:${px}px;top:${py}px;width:${g.dw * k}px;height:${g.dh * k}px` }));
      } else {
        win.classList.add("draggable");
        win.title = "Drag up or down (or sideways) to choose the part you see";
        win.append(el("img", { class: "desk-img", src: thumbUrl(t.p.name, true), alt: t.p.title, draggable: "false",
          style: `left:${px}px;top:${py}px;width:${g.dw * k}px;height:${g.dh * k}px` }));
      }
      if ($("label").checked && withLabel.has(m)) win.append(labelChip(t.p, m, k, st));
    } else {
      win.append(el("span", { class: "desk-empty" },
        cur.rot.count ? "Nothing from Masterpiece here yet" : "Your collection is still empty"));
    }
    win.append(el("span", { class: "dim" }, `${m.width}×${m.height}${m.primary && mons.length > 1 ? " · main" : ""}`));
    kids.push(win);
  });

  // "cut off · 29%" in the biggest faded strip of each painting
  targets.forEach((t) => {
    if (!t.p) return;
    const g = placePainting(t.p, t.box.w, t.box.h);
    if (g.whole || g.cut < 0.02) return;
    const strips = [["top", -g.y], ["bottom", g.y + g.dh - t.box.h], ["left", -g.x], ["right", g.x + g.dw - t.box.w]];
    const [side, size] = strips.sort((a, b) => b[1] - a[1])[0];
    const bx = ox + t.box.x * k, by = oy + t.box.y * k, bw = t.box.w * k, bh = t.box.h * k, s = size * k;
    const pos = side === "top" ? [bx + bw / 2, by - s / 2] : side === "bottom" ? [bx + bw / 2, by + bh + s / 2]
      : side === "left" ? [bx - s / 2, by + bh / 2] : [bx + bw + s / 2, by + bh / 2];
    if (s > 16) kids.push(el("span", { class: "desk-cut", style: `left:${pos[0]}px;top:${pos[1]}px` },
      "cut off · ", el("b", {}, `${Math.round(g.cut * 100)}%`)));
  });
  stage.replaceChildren(...kids);
  for (const c of stage.querySelectorAll(".chip-label")) placeChip(c);
  autoTones();
  renderCaptions(targets, mons, k, ox, (W + padL + padR) * k);
}

function labelChip(p, m, k, st) {
  const lines = labelLines(p, st.text);
  let px = (Math.min(m.width, m.height) / (LABEL_SIZE_DIV[st.size] || 55)) * k;
  if (st.look === "subtle") px *= 0.85;
  const chip = el("span", { class: `chip-label look-${st.look} font-${st.font}${lines.length > 1 ? " two" : ""}`,
                            title: "Drag to move the label" },
    ...lines.map((t, i) => el("span", { class: i ? "l2" : "l1" }, t)));
  chip.style.fontSize = `${Math.max(7, px)}px`;
  return chip;
}

function placeChip(chip) {
  const pos = cur.s.labelPos || { x: 0.5, y: 0.93 };
  const s = chip.parentElement, sw = s.clientWidth, sh = s.clientHeight, cw = chip.offsetWidth, ch = chip.offsetHeight;
  const m = parseFloat(chip.style.fontSize) || 8;
  chip.style.left = `${Math.min(Math.max(pos.x * sw, m + cw / 2), sw - m - cw / 2)}px`;
  chip.style.top = `${Math.min(Math.max(pos.y * sh, m + ch / 2), sh - m - ch / 2)}px`;
  chip.style.textAlign = pos.x < 0.34 ? "left" : pos.x > 0.66 ? "right" : "center";
}

// "Auto" label: dark text where the painting is light under the label, like the real one
function autoTones() {
  for (const chip of document.querySelectorAll("#deskStage .chip-label.look-auto")) {
    const win = chip.parentElement, im = win.querySelector(".desk-img");
    if (!im) continue;
    const measure = () => {
      try {
        const c = document.createElement("canvas"), w = win.clientWidth, h = win.clientHeight;
        c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
        const g = c.getContext("2d", { willReadFrequently: true });
        g.drawImage(im, parseFloat(im.style.left) || 0, parseFloat(im.style.top) || 0, im.offsetWidth, im.offsetHeight);
        const x = chip.offsetLeft - chip.offsetWidth / 2, y = chip.offsetTop - chip.offsetHeight / 2;
        const d = g.getImageData(Math.max(0, x), Math.max(0, y), Math.max(1, chip.offsetWidth), Math.max(1, chip.offsetHeight)).data;
        let sum = 0;
        for (let i = 0; i < d.length; i += 4) sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        chip.classList.toggle("on-light", sum / (d.length / 4) / 255 > AUTO_BRIGHT);
      } catch { /* image not ready */ }
    };
    if (im.complete && im.naturalWidth) measure(); else im.addEventListener("load", measure, { once: true });
  }
}

function screenName(m, mons) {
  if (mons.length < 2) return "Your screen";
  if (m.primary) return "Main";
  const xs = mons.map((x) => x.x);
  return m.x === Math.min(...xs) ? "Left" : m.x === Math.max(...xs) ? "Right" : "Screen";
}

function renderCaptions(targets, mons, k, ox, width) {
  const shown = targets.filter((t) => t.p).sort((a, b) => a.box.x - b.box.x);
  const caps = $("deskCaps");
  caps.style.width = `${width}px`;
  caps.style.gridTemplateColumns = shown.map((t) => `${t.box.w * k}px`).join(" ");
  caps.style.paddingLeft = `${ox + (shown[0] ? shown[0].box.x * k : 0)}px`;
  caps.replaceChildren(...shown.map((t) => {
    const p = t.p, g = placePainting(p, t.box.w, t.box.h);
    const where = t.mons.length > 1 ? "Across all screens" : screenName(t.mons[0], mons);
    const tags = [];
    if (p.focus && !g.whole) {
      tags.push(el("button", { type: "button", class: "tag gold", title: "Back to the setting for all paintings",
        onclick: () => saveCrop(p.name, null) }, "your crop ✕"));
    }
    if (g.whole) tags.push(el("span", { class: "tag" }, "whole painting"));
    if (isSoft(p, t.box.w, t.box.h)) tags.push(el("span", { class: "tag warn", title: `Only ${p.w}×${p.h} px: it is enlarged to fill the screen` }, "⚠ a bit soft"));
    return el("div", { class: "desk-cap" },
      el("span", { class: m0(t, mons) ? "main" : "" }, `${where} · `),
      el("a", { href: `painting.html?name=${encodeURIComponent(p.name)}` }, el("b", {}, p.title)),
      p.maker ? ` — ${[p.maker, p.year].filter(Boolean).join(", ")}` : "", ...tags);
  }));
}
const m0 = (t, mons) => t.mons.length === 1 && t.mons[0].primary && mons.length > 1;

// ------------------------------------------------------------------ dragging (painting and label)
function setupDeskDrag() {
  const stage = $("deskStage");
  stage.addEventListener("pointerdown", (e) => {
    const chip = e.target.closest(".chip-label"), win = e.target.closest(".desk-screen");
    if (!win) return;
    if (chip) {
      desk.drag = { kind: "label", win };
    } else if (win.classList.contains("draggable") && win.dataset.name) {
      const t = deskTargets().targets.find((x) => x.p && x.p.name === win.dataset.name);
      if (!t) return;
      const g = placePainting(t.p, t.box.w, t.box.h);
      const k = win.clientWidth / Number(win.dataset.w);      // preview px per screen px
      desk.drag = { kind: "paint", name: t.p.name, sx: e.clientX, sy: e.clientY, cx: g.cx, cy: g.cy,
                    rx: (g.dw - t.box.w) * k, ry: (g.dh - t.box.h) * k };
    } else return;
    stage.setPointerCapture(e.pointerId);
    stage.classList.add("dragging");
    e.preventDefault();
  });
  stage.addEventListener("pointermove", (e) => {
    const d = desk.drag;
    if (!d) return;
    if (d.kind === "label") {
      const r = d.win.getBoundingClientRect();
      let x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
      if (Math.abs(x - 0.5) < 0.025) x = 0.5;           // gentle snap to the centre line
      cur.s.labelPos = { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 };
      for (const c of stage.querySelectorAll(".chip-label")) placeChip(c);
    } else {
      const cx = d.rx > 0.5 ? Math.min(1, Math.max(0, d.cx - (e.clientX - d.sx) / d.rx)) : d.cx;
      const cy = d.ry > 0.5 ? Math.min(1, Math.max(0, d.cy - (e.clientY - d.sy) / d.ry)) : d.cy;
      desk.live[d.name] = [cx, cy];
      renderDesk();
    }
  });
  const end = () => {
    const d = desk.drag;
    if (!d) return;
    desk.drag = null;
    stage.classList.remove("dragging");
    if (d.kind === "label") {
      saveSettings({ labelPos: cur.s.labelPos }).then(() => $("label").checked && refreshLabel());
      autoTones();
    } else if (desk.live[d.name]) {
      saveCrop(d.name, desk.live[d.name].map((v) => Math.round(v * 1000) / 1000));
    }
  };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);
  addEventListener("resize", () => renderDesk());
}

async function saveCrop(name, focus) {
  try {
    const r = await api("/api/rotation", { action: "crop", name, focus });
    delete desk.live[name];
    setRotation(r);                                      // re-renders the preview with the saved crop
  } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ the settings beside it
function syncDeskControls() {
  const st = style(), two = (cur.rot.screens || cur.options.screens || []).length > 1;
  const pick = (id, v) => {
    for (const b of $(id).querySelectorAll("button")) {
      b.classList.toggle("on", b.dataset.v === v);
      b.setAttribute("aria-checked", String(b.dataset.v === v));
    }
  };
  $("rowScreens").hidden = !two;
  $("rowWhere").hidden = !two;
  pick("segScreens", cur.s.screens || "each");
  pick("segCrop", cropMode());
  pick("segEdges", cur.s.edges || "blur");
  $("rowEdges").hidden = cropMode() !== "whole";
  pick("segWhere", st.where);
  pick("segLook", st.look);
  pick("segFont", st.font);
  pick("segSize", st.size);
  $("labelText").value = st.text;
  $("label").checked = !!cur.s.label;
  $("labelOpts").classList.toggle("dim", !cur.s.label);
  $("cropNote").textContent = cropMode() === "whole"
    ? "Nothing is cut off; the empty edges are filled. Good for portraits and square paintings."
    : "The faded part is cut off. Drag a painting to choose the part yourself: it keeps your choice.";
}

function changed(updates, now = false) {               // save, then show it on the desktop too
  Object.assign(cur.s, updates);
  syncDeskControls();
  renderDesk();
  clearTimeout(desk.timer);
  desk.timer = setTimeout(async () => {
    await saveSettings(updates);
    refreshLabel();
  }, now ? 0 : 250);
}

function setupDesk() {
  const seg = (id, fn) => $(id).addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (b) fn(b.dataset.v);
  });
  seg("segScreens", (v) => changed({ screens: v }, true));
  seg("segCrop", (v) => changed({ crop: v }));
  seg("segEdges", (v) => changed({ edges: v }));
  const setStyle = (k) => (v) => changed({ labelStyle: { ...style(), [k]: v } });
  seg("segWhere", setStyle("where"));
  seg("segLook", setStyle("look"));
  seg("segFont", setStyle("font"));
  seg("segSize", setStyle("size"));
  $("labelText").addEventListener("change", () => setStyle("text")($("labelText").value));
  $("label").addEventListener("change", () => changed({ label: $("label").checked }, true));
  for (const b of document.querySelectorAll("#labelPresets [data-pos]")) {
    b.addEventListener("click", () => {
      const [x, y] = b.dataset.pos.split(",").map(Number);
      changed({ labelPos: { x, y } });
    });
  }
  setupDeskDrag();
  setupUpcoming();
  syncDeskControls();
}

// ------------------------------------------------------------------ coming next
function renderUpcoming() {
  const list = cur.rot.upcoming || [];
  $("deskNext").hidden = !list.length;
  const mons = cur.rot.screens || [];
  const best = (p) => {                                  // the screen whose shape suits it best
    if (!mons.length || !p.w) return null;
    const r = p.w / p.h;
    return mons.reduce((a, m) => (Math.abs(Math.log(r / (m.width / m.height))) < Math.abs(Math.log(r / (a.width / a.height))) ? m : a));
  };
  $("nextRow").replaceChildren(...list.map((p) => {
    const m = best(p);
    return el("div", { class: "nx", draggable: "true", "data-name": p.name, title: "Drag to change the order" },
      el("img", { src: thumbUrl(p.name), alt: "", draggable: "false" }),
      el("span", {}, el("b", {}, p.title),
        [p.maker, p.year].filter(Boolean).join(", "),
        m && isSoft(p, m.width, m.height) ? el("span", { class: "tag warn", title: `Only ${p.w}×${p.h} px` }, "⚠ a bit soft") : null),
      el("button", { type: "button", class: "x", title: "Not now", "aria-label": `Skip ${p.title}`,
        onclick: () => rotation("skipNext", { name: p.name }) }, "×"));
  }));
}

function setupUpcoming() {
  let dragged = null;
  const row = $("nextRow");
  row.addEventListener("dragstart", (e) => { dragged = e.target.closest(".nx"); if (dragged) dragged.classList.add("moving"); });
  row.addEventListener("dragover", (e) => {
    if (!dragged) return;
    e.preventDefault();
    const over = e.target.closest(".nx");
    if (!over || over === dragged) return;
    const r = over.getBoundingClientRect();
    row.insertBefore(dragged, e.clientX > r.left + r.width / 2 ? over.nextSibling : over);
  });
  row.addEventListener("dragend", () => {
    if (!dragged) return;
    dragged.classList.remove("moving");
    dragged = null;
    rotation("queue", { order: [...row.querySelectorAll(".nx")].map((n) => n.dataset.name) });
  });
}
