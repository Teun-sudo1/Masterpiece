"use strict";
// "About this painting": text, facts, Save or share, and a few lines from Wikipedia.
// Used beside the preview on the Curator tab (compact) and on painting.html (full). Needs shell.js.

async function renderAbout(box, name, opts = {}) {
  const { compact = false, onChange = null } = opts;
  box.dataset.name = name;
  box.replaceChildren(el("p", { class: "muted" }, "Loading…"));
  let p;
  try {
    p = await api(`/api/painting?name=${encodeURIComponent(name)}`);
  } catch (e) {
    if (box.dataset.name === name) box.replaceChildren(el("p", { class: "muted" }, e.message));
    return null;
  }
  if (box.dataset.name !== name) return null;             // another painting was chosen meanwhile
  const again = () => (onChange ? onChange(p) : renderAbout(box, name, opts));
  const act = (body, done) => api("/api/collection", body).then(done).catch((e) => toast(`Didn't work: ${e.message}`));
  const d = p.details || {};
  const facts = [["Date", p.year], ["Museum", p.museum], ...(d.facts || []),
                 ["Image", p.width ? `${p.width} × ${p.height} px` : ""], ["Licence", p.license]].filter(([, v]) => v);
  const note = el("p", { class: "keep-note", hidden: true });
  const wiki = el("div", { class: "wiki" });
  const fit = el("div", { class: "fit", id: "fit" });
  const noDesc = el("p", { class: "muted" }, p.detailsError || (p.link ? "The museum's own page has more about this painting." : ""));

  async function keep(action, kind) {
    try {
      const r = await api("/api/collection", { action, kind, name });
      note.replaceChildren(...(action === "copy"
        ? ["Copied. Paste it into a chat or an e-mail (Ctrl+V)."]
        : [`Saved “${r.file}” in Pictures › Saved from Masterpiece. `,
           el("button", { type: "button", class: "link",
             onclick: () => api("/api/collection", { action: "reveal", path: r.path }).catch((e) => toast(e.message)) }, "Show in folder")]));
      note.hidden = false;
    } catch (e) { toast(`Didn't work: ${e.message}`); }
  }

  const museumBtn = p.link ? el("a", { class: "button", href: p.link, target: "_blank", rel: "noopener" }, "Museum page ↗") : null;
  box.replaceChildren(
    ...(compact ? [] : [el("div", { class: "pic" },
      el("img", { src: `/api/thumb?name=${encodeURIComponent(p.name)}&size=large`, alt: p.title }))]),
    el("div", { class: "about-text" },
      el(compact ? "h3" : "h2", {}, p.title),
      el("p", { class: "who" }, [p.maker, p.year].filter(Boolean).join(", ")),
      ...(p.curator ? [el("p", { class: "curator" }, el("b", {}, "Chosen by the Curator: "), p.curator)] : []),
      ...(p.fromCurator ? [el("p", { class: "muted from-cur" }, "In the Curator's collection. ",
        el("button", { type: "button", class: "link",
          onclick: () => act({ action: "keep", name }, () => { toast("It's in My collection now."); again(); }) },
          "Keep it in My collection"))] : []),
      ...(compact ? [] : [
        el("div", { class: "pills" },
          ...p.screens.map((s) => el("span", { class: "now" }, `On screen now · ${s}`)),
          ...(p.favourite ? [el("span", {}, "♥ Favourite")] : [])),
        el("div", { class: "actions" },
          el("button", { type: "button", class: "primary", onclick: () => act({ action: "show", name }, again) }, "Show now"),
          el("button", { type: "button", class: `fav${p.favourite ? " on" : ""}`,
            onclick: () => act({ action: "favourite", name, on: !p.favourite }, again) }, p.favourite ? "♥ Favourite" : "♡ Favourite"),
          el("button", { type: "button", title: "Remove it from your collection and show another painting there",
            onclick: () => act({ action: "skip", name }, () => location.replace("collection.html")) }, "Skip"),
          museumBtn)]),
      el("div", { class: "keep" },
        el("span", {}, "Keep or share:"),
        el("button", { type: "button", class: "small", title: "The full picture, without the label, in Pictures › Saved from Masterpiece",
          onclick: () => keep("save", "picture") }, "Save picture"),
        el("button", { type: "button", class: "small", title: "The painting on a card with its title, artist and museum underneath",
          onclick: () => keep("save", "postcard") }, "Save as postcard"),
        el("button", { type: "button", class: "small", title: "Copy the postcard, then paste it into a chat or an e-mail",
          onclick: () => keep("copy", "postcard") }, "Copy postcard"),
        ...(compact && p.link ? [el("a", { class: "small-link", href: p.link, target: "_blank", rel: "noopener" }, "Museum page ↗")] : []),
        note),
      d.description ? el("p", { class: "desc" }, d.description) : noDesc,
      ...(compact ? [] : [fit]),
      wiki,
      el("dl", {}, ...facts.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))])),
      ...(d.credit ? [el("p", { class: "muted" }, d.credit)] : [])));

  if (!compact) renderFit(fit, p);

  // Wikipedia after the rest is shown (a few small requests, then kept for 30 days)
  api(`/api/about?name=${encodeURIComponent(name)}`).then((w) => {
    if (box.dataset.name !== name) return;
    const more = (x) => el("a", { href: x.url, target: "_blank", rel: "noopener" }, "Read more on Wikipedia ↗");
    const parts = [];
    if (w.painting) {
      if (!d.description) noDesc.remove();
      parts.push(el("h4", {}, "About this painting"), el("p", {}, w.painting.text), more(w.painting));
    }
    if (w.artist) parts.push(el("h4", {}, `About ${w.artist.title}`), el("p", {}, w.artist.text), more(w.artist));
    if (w.credit) parts.push(el("p", { class: "muted credit" }, w.credit));
    wiki.replaceChildren(...parts);
  }).catch(() => {});
  return p;
}

// ------------------------------------------------------------------ on your screens (full page)
// How the painting fits each of your screen shapes: the faded part is cut off, the slider
// beside (top … bottom) or under it (left … right) chooses the part you see. The choice is
// kept for this painting, also for later (settings "crops"), like the slider in Settings.
const FIT_AT = { middle: [0.5, 0.5], bottom: [0.5, 1], top: [0.5, 0] };   // same as wallpaper.CROPS
const FIT_LABEL = { middle: "Middle", bottom: "Bottom", top: "Top" };

function fitShapes(rot, s) {
  const mons = (rot.screens && rot.screens.length) ? rot.screens : [{ width: 1920, height: 1080, primary: true }];
  if (s.screens === "span" && mons.length > 1) {
    const w = Math.max(...mons.map((m) => m.x + m.width)) - Math.min(...mons.map((m) => m.x));
    const h = Math.max(...mons.map((m) => m.y + m.height)) - Math.min(...mons.map((m) => m.y));
    return [{ w, h, label: "Across all screens" }];
  }
  const seen = new Map();
  for (const m of mons) {
    const key = `${m.width}×${m.height}`;
    if (!seen.has(key)) seen.set(key, { w: m.width, h: m.height, label: key + (m.primary && mons.length > 1 ? " · main" : "") });
  }
  return [...seen.values()];
}

function fitPlace(iw, ih, w, h, at) {
  const sc = Math.max(w / iw, h / ih), dw = iw * sc, dh = ih * sc;
  return { dw, dh, x: -(dw - w) * at[0], y: -(dh - h) * at[1], cut: 1 - (w * h) / (dw * dh),
           vertical: dh - h >= dw - w };
}

async function renderFit(box, p) {
  let rot, s;
  try { [rot, s] = await Promise.all([api("/api/rotation"), api("/api/settings")]); } catch { return; }
  const mode = s.crop || "middle";
  if (!p.width || !p.height) return;
  const head = el("h4", {}, "On your screens");
  if (mode === "whole") {
    box.replaceChildren(head, el("p", { class: "muted" },
      "“Whole painting” is on (Settings › Your screens): nothing is cut off, the edges are filled."));
    return;
  }
  const own = (s.crops || {})[p.name];
  let at = own ? [...own] : [...(FIT_AT[mode] || FIT_AT.middle)];
  const shapes = fitShapes(rot, s);
  const MAXW = 300, MAXH = 170, ROOM = 24;
  const stages = [];
  const note = el("p", { class: "fit-note" });

  function sayNote() {
    const mine = !!(s.crops || {})[p.name];
    note.replaceChildren(...(mine
      ? [el("b", {}, "Saved for this painting, also for later: "), "every time it comes on your screens, you see this part. ",
         el("button", { type: "button", class: "link", onclick: () => save(null) }, `Back to the setting (${FIT_LABEL[mode] || mode})`)]
      : [`Now: “${FIT_LABEL[mode] || mode}”, the setting for all paintings. Slide to choose the part yourself: it's saved for this painting, also for later.`]));
  }

  async function save(focus) {
    try {
      await api("/api/rotation", { action: "crop", name: p.name, focus });
      s.crops = { ...(s.crops || {}) };
      if (focus) s.crops[p.name] = focus; else delete s.crops[p.name];
      if (!focus) at = [...(FIT_AT[mode] || FIT_AT.middle)];
      draw();
      sayNote();
    } catch (e) { toast(`Couldn't save: ${e.message}`); }
  }

  function draw() {
    for (const st of stages) st.place();
  }

  const src = `/api/thumb?name=${encodeURIComponent(p.name)}&size=large`;
  const grid = el("div", { class: "fit-grid" }, ...shapes.map((sh) => {
    const k = Math.min(MAXW / sh.w, MAXH / sh.h), sw = sh.w * k, shh = sh.h * k;
    const g0 = fitPlace(p.width, p.height, sh.w, sh.h, at);
    const cuts = g0.cut > 0.01;
    // room around the screen for the faded part (as big as it can get, so nothing jumps while sliding)
    const padX = cuts && !g0.vertical ? (g0.dw - sh.w) * k : 0, padY = cuts && g0.vertical ? (g0.dh - sh.h) * k : 0;
    const left = cuts && g0.vertical ? ROOM : 0, below = cuts && !g0.vertical ? ROOM : 0;
    const stage = el("div", { class: "fit-stage", style: `width:${left + padX * 2 + sw}px;height:${padY * 2 + shh + below}px` });
    const ghost = el("img", { class: "fit-ghost", src, alt: "" });
    const inner = el("img", { class: "fit-img", src, alt: "" });
    const screen = el("div", { class: "fit-screen", style: `left:${left + padX}px;top:${padY}px;width:${sw}px;height:${shh}px` }, inner,
      el("span", { class: "fit-dim" }, sh.label));
    const cutTag = el("span", { class: "fit-cut" });
    stage.append(ghost, screen, cutTag);
    let slider = null;
    if (cuts) {
      slider = el("input", { type: "range", min: "0", max: "1000", step: "1", class: `desk-slider fit-slider ${g0.vertical ? "v" : "h"}`,
        "aria-label": g0.vertical ? `Which part of “${p.title}” on ${sh.label}: top to bottom` : `Which part of “${p.title}” on ${sh.label}: left to right`,
        title: g0.vertical ? "Slide to choose which part you see: top … bottom" : "Slide to choose which part you see: left … right",
        style: g0.vertical ? `left:${ROOM / 2 - 6}px;top:${padY}px;height:${shh}px` : `left:${left + padX}px;top:${padY * 2 + shh + below / 2 - 6}px;width:${sw}px` });
      slider.addEventListener("input", () => {
        const v = Number(slider.value) / 1000;
        at = g0.vertical ? [at[0], v] : [v, at[1]];
        draw();
      });
      slider.addEventListener("change", () => save(at.map((x) => Math.round(x * 1000) / 1000)));
      stage.append(slider);
    }
    stages.push({ place() {
      const g = fitPlace(p.width, p.height, sh.w, sh.h, at);
      const x = g.x * k, y = g.y * k, w = g.dw * k, h = g.dh * k;
      Object.assign(ghost.style, { left: `${left + padX + x}px`, top: `${padY + y}px`, width: `${w}px`, height: `${h}px`, display: cuts ? "" : "none" });
      Object.assign(inner.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
      cutTag.textContent = cuts ? `cut off · ${Math.round(g.cut * 100)}%` : "fits: nothing cut off";
      if (slider && document.activeElement !== slider) slider.value = String(Math.round((g.vertical ? at[1] : at[0]) * 1000));
    } });
    return el("figure", { class: "fit-item" }, stage);
  }));
  box.replaceChildren(head, grid, note);
  draw();
  sayNote();
}
