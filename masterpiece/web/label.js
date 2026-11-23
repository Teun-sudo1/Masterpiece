"use strict";
// The label style & position dialog (used on the Curator tab). Needs shell.js.

const LABEL_SIZE_DIV = { s: 72, m: 55, l: 40 };      // same as wallpaper.LABEL_SIZES
const LABEL_OPTIONS = {
  look: [["dark", "Dark"], ["light", "Light"], ["plaque", "Museum plaque"], ["shadow", "Shadow"], ["subtle", "Subtle"]],
  text: [["full", "Title — Artist, year · Museum"], ["two", "Two lines"], ["artist", "Title — Artist, year"], ["title", "Title (year)"]],
  font: [["sans", "Sans"], ["serif", "Serif"]],
  size: [["s", "S"], ["m", "M"], ["l", "L"]],
  where: [["all", "All screens"], ["main", "Main screen"], ["left", "Left screen"], ["right", "Right screen"]],
};
const PRESETS = [["0.5,0.93", "bottom centre"], ["0.5,0.5", "centre"], ["0.86,0.93", "bottom right"], ["0.5,0.07", "top centre"]];

const labelDlg = { pos: { x: 0.5, y: 0.93 }, style: { look: "dark", font: "sans", size: "m", text: "full", where: "all" },
                   screens: [], sample: null, onDone: null };

function labelLines(a, mode) {          // mirrors wallpaper.label_lines (with the painting's date)
  const j = (sep, ...xs) => xs.filter(Boolean).join(sep);
  const year = String(a.year || "").trim().slice(0, 24);
  const by = j(", ", a.maker, year);
  if (mode === "title") return [year ? `${a.title} (${year})` : a.title];
  if (mode === "artist") return [j(" — ", a.title, by)];
  if (mode === "two") return [a.title, j(" · ", by, a.museum)];
  return [j(" · ", j(" — ", a.title, by), a.museum)];
}

// mirrors wallpaper.labelled_screens: which screens show the label
function labelledScreens(scr, where) {
  if (scr.length < 2 || !["main", "left", "right"].includes(where)) return new Set(scr);
  let pick;
  if (where === "main") pick = scr.find((m) => m.primary) || scr[0];
  else if (where === "left") pick = scr.reduce((a, m) => (m.x < a.x || (m.x === a.x && m.y < a.y) ? m : a));
  else pick = scr.reduce((a, m) => (m.x + m.width > a.x + a.width || (m.x + m.width === a.x + a.width && m.y < a.y) ? m : a));
  return new Set([pick]);
}

function buildLabelDialog() {
  if ($("labelDlg")) return;
  const seg = (key) => el("span", { class: "seg", "data-key": key },
    ...LABEL_OPTIONS[key].map(([v, t]) => el("button", { type: "button", "data-v": v, class: v === "serif" ? "serif" : "" }, t)));
  const dlg = el("dialog", { id: "labelDlg", class: "label-dlg" },
    el("h2", {}, "Label style & position"),
    el("p", { class: "hint" }, "Pick a look, then drag the label on any screen. The same style and spot are used on every screen."),
    el("div", { class: "label-styles", id: "labelStyles" },
      el("div", { class: "seg-group" }, el("span", { class: "lbl" }, "Look"), seg("look")),
      el("div", { class: "seg-group" }, el("span", { class: "lbl" }, "Text"), seg("text")),
      el("div", { class: "seg-group" }, el("span", { class: "lbl" }, "Font"), seg("font"),
        el("span", { class: "lbl" }, "Size"), seg("size")),
      el("div", { class: "seg-group", id: "labelWhere" }, el("span", { class: "lbl" }, "Screens"), seg("where"))),
    el("div", { class: "screens-stage", id: "labelStage" }),
    el("div", { class: "dlg-actions" },
      el("span", { class: "presets" },
        ...PRESETS.map(([pos, t]) => el("button", { type: "button", class: "link", "data-pos": pos }, t))),
      el("button", { type: "button", class: "primary", id: "labelDone" }, "Done")));
  document.body.append(dlg);

  const stage = $("labelStage");
  let dragging = null;
  const move = (e) => {
    if (!dragging) return;
    const r = dragging.getBoundingClientRect();
    let x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    const snap = Math.abs(x - 0.5) < 0.025;        // gentle snap to the vertical centre line
    if (snap) x = 0.5;
    labelDlg.pos = { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 };
    placeChips(snap);
  };
  stage.addEventListener("pointerdown", (e) => {
    const s = e.target.closest(".screen");
    if (!s) return;
    dragging = s;
    stage.classList.add("dragging");
    stage.setPointerCapture(e.pointerId);
    move(e);
  });
  stage.addEventListener("pointermove", move);
  const end = () => { if (dragging) { dragging = null; stage.classList.remove("dragging"); placeChips(false); } };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);
  for (const b of dlg.querySelectorAll(".presets [data-pos]")) {
    b.addEventListener("click", () => {
      const [x, y] = b.dataset.pos.split(",").map(Number);
      labelDlg.pos = { x, y };
      placeChips();
    });
  }
  for (const sg of dlg.querySelectorAll("#labelStyles .seg")) {
    sg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-v]");
      if (!b) return;
      labelDlg.style = { ...labelDlg.style, [sg.dataset.key]: b.dataset.v };
      syncStyleButtons();
      renderLabelStage();
    });
  }
  $("labelDone").addEventListener("click", () => dlg.close());
  dlg.addEventListener("close", () => labelDlg.onDone && labelDlg.onDone(labelDlg.pos, labelDlg.style));
}

function syncStyleButtons() {
  for (const sg of document.querySelectorAll("#labelStyles .seg")) {
    for (const b of sg.querySelectorAll("button")) {
      const on = labelDlg.style[sg.dataset.key] === b.dataset.v;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    }
  }
}

function openLabelDialog({ screens, sample, pos, style, onDone }) {
  buildLabelDialog();
  Object.assign(labelDlg, { screens: screens || [], sample, onDone,
                            pos: pos || labelDlg.pos, style: { ...labelDlg.style, ...(style || {}) } });
  syncStyleButtons();
  $("labelDlg").showModal();          // first, so the chips can be measured
  renderLabelStage();
}

function renderLabelStage() {
  const stage = $("labelStage");
  const scr = labelDlg.screens.length ? labelDlg.screens : [{ x: 0, y: 0, width: 1920, height: 1080, primary: true }];
  $("labelWhere").hidden = scr.length < 2;                // only a choice with more than one screen
  const withLabel = labelledScreens(scr, labelDlg.style.where);
  const x0 = Math.min(...scr.map((m) => m.x)), y0 = Math.min(...scr.map((m) => m.y));
  const W = Math.max(...scr.map((m) => m.x + m.width)) - x0, H = Math.max(...scr.map((m) => m.y + m.height)) - y0;
  const maxW = Math.min(700, window.innerWidth * 0.86), maxH = Math.min(360, window.innerHeight * 0.5);
  const scale = Math.min(maxW / W, maxH / H);
  stage.style.width = `${W * scale}px`;
  stage.style.height = `${H * scale}px`;
  const a = labelDlg.sample || { title: "Title", maker: "Artist", year: "1880", museum: "Museum" };
  const lines = labelLines(a, labelDlg.style.text);
  const st = labelDlg.style;
  stage.replaceChildren(...scr.map((m) => {
    let fontPx = (Math.min(m.width, m.height) / (LABEL_SIZE_DIV[st.size] || 55)) * scale;
    if (st.look === "subtle") fontPx *= 0.85;
    const chip = el("span", { class: `chip-label look-${st.look} font-${st.font}${lines.length > 1 ? " two" : ""}` },
      ...lines.map((t, i) => el("span", { class: i ? "l2" : "l1" }, t)));
    chip.style.fontSize = `${Math.max(6, fontPx)}px`;
    if (!withLabel.has(m)) chip.hidden = true;           // this screen shows no label
    const s = el("div", { class: "screen" },
      el("span", { class: "dim" }, `${fmt(m.width, m.height)}${m.primary ? " · main" : ""}`),
      el("span", { class: "guide" }), chip);
    Object.assign(s.style, {
      left: `${(m.x - x0) * scale}px`, top: `${(m.y - y0) * scale}px`,
      width: `${m.width * scale}px`, height: `${m.height * scale}px`,
    });
    if (a.thumb) s.style.backgroundImage = `url("${a.thumb}")`;
    return s;
  }));
  placeChips();
}

function placeChips(snapping = false) {
  const { x, y } = labelDlg.pos;
  const align = x < 0.34 ? "left" : x > 0.66 ? "right" : "center";    // like the real label
  for (const s of $("labelStage").querySelectorAll(".screen")) {
    const chip = s.querySelector(".chip-label");
    const sw = s.clientWidth, sh = s.clientHeight, cw = chip.offsetWidth, ch = chip.offsetHeight;
    const m = parseFloat(chip.style.fontSize) || 8;
    chip.style.left = `${Math.min(Math.max(x * sw, m + cw / 2), sw - m - cw / 2)}px`;
    chip.style.top = `${Math.min(Math.max(y * sh, m + ch / 2), sh - m - ch / 2)}px`;
    chip.style.textAlign = align;
    s.classList.toggle("snap", snapping);
  }
}
