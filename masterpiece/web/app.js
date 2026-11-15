"use strict";

const $ = (id) => document.getElementById(id);
const img = (url) => `/api/img?u=${encodeURIComponent(url)}`;

const state = {
  sources: [],
  options: { subjects: [], periods: [], regions: [], hide: [], screens: [], span: null },
  results: [],
  cursors: {},             // source key -> next page (0 = nothing more)
  selected: new Map(),     // id -> artwork
  showingSelection: false,
  loading: false,
  saved: new Set(),        // ids already in the collection folder
  gen: 0,                  // search generation, to drop stale responses
  pending: new Set(),      // museums still answering
  errors: {},
  skipped: new Set(),      // museums without works from the chosen region
  lbIndex: -1,
  labelPos: { x: 0.5, y: 0.93 },
  labelStyle: { look: "dark", font: "sans", size: "m", text: "full" },
};

const LABEL_SIZE_DIV = { s: 72, m: 55, l: 40 };      // same as wallpaper.LABEL_SIZES

const PRESET_INTERVALS = [10, 30, 60, 180, 1440];

// ------------------------------------------------------------------ api
async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

const hideValues = () => [...document.querySelectorAll("#hide input:checked")].map((i) => i.value);

let saveTimer;
function saveSettings() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveNow().catch((e) => toast(`Could not save settings: ${e.message}`)), 400);
}

function saveNow() {
  clearTimeout(saveTimer);
  return api("/api/settings", {
      enabledSources: state.sources.filter((s) => s.enabled).map((s) => s.key),
      query: $("q").value.trim(),
      color: $("color").value,
      topOnly: $("topOnly").checked,
      region: $("region").value,
      subject: $("subject").value,
      period: $("period").value,
      hide: hideValues(),
      minWidth: $("minWidth").value,
      orientation: $("orientation").value,
      label: $("label").checked,
      labelPos: state.labelPos,
      labelStyle: state.labelStyle,
      mode: $("mode").value,
      interval: intervalMinutes(),
      selection: [...state.selected.values()],      // screens, maxFiles, timeOfDay: on the Settings page
  });
}

// Label changed: save, then re-render the paintings that are on screen now
let labelBusy = Promise.resolve();
function applyLabelNow() {
  labelBusy = labelBusy.then(async () => {
    try {
      await saveNow();
      const r = await api("/api/rotation", { action: "refresh" });
      if (r.slideshow) toast("Label updated. The Windows slideshow shows it from this picture on.");
      else if (Object.keys(r.wallpapers || {}).length) toast("Label updated on your desktop.");
      else toast("Label saved. It's used from the next painting on.");
    } catch (e) {
      toast(`Couldn't update the label: ${e.message}`);
    }
  });
  return labelBusy;
}

// ------------------------------------------------------------------ ui helpers
function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) n.append(c);
  return n;
}

let toastTimer;
function toast(msg, ms = 5000) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

function currentList() {
  return state.showingSelection ? [...state.selected.values()] : state.results;
}

const fmt = (w, h) => `${w}×${h}`;

const ICONS = { plus: "M12 5v14M5 12h14", check: "M5 12.5l4.5 4.5L19 7" };
function icon(name) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

// ------------------------------------------------------------------ options
function renderOptions(s) {
  const o = state.options;
  for (const x of o.regions || []) $("region").append(el("option", { value: x.key }, x.label));
  for (const x of o.subjects) $("subject").append(el("option", { value: x.key }, x.label));
  for (const x of o.periods) $("period").append(el("option", { value: x.key }, x.label));
  for (const x of o.hide) {
    $("hide").append(el("label", { class: "check" },
      el("input", { type: "checkbox", value: x.key, checked: (s.hide || []).includes(x.key) }), x.label));
  }

  const scr = o.screens;
  if (scr.length) {
    const parts = scr.map((m) => {
      const kind = m.height > m.width ? " portrait" : "";
      return `<b>${fmt(m.width, m.height)}</b>${kind}${m.primary && scr.length > 1 ? " (main)" : ""}`;
    });
    $("screenInfo").innerHTML = `Your screen${scr.length > 1 ? "s" : ""}: ${parts.join(" · ")}` +
      (scr.length > 1 && o.span ? ` — together ${fmt(o.span.width, o.span.height)}` : "");
    $("optSharp").textContent = `Sharp on my screen${scr.length > 1 ? "s" : ""} (${scr.map((m) => fmt(m.width, m.height)).join(" / ")})`;
    if (o.span) $("optSpan").textContent = `Spans all my screens (${fmt(o.span.width, o.span.height)})`;
  } else {
    $("screenInfo").textContent = "Screen size unknown — assuming 1920×1080.";
  }
  const multi = scr.length > 1;
  $("optSpan").hidden = !multi;
  $("optSpan").disabled = !multi;
}

// ------------------------------------------------------------------ region map
// Simplified continents as [longitude, latitude] outlines, drawn equirectangular.
const MAP_LAND = {
  americas: [
    [[-168, 66], [-140, 70], [-95, 72], [-80, 63], [-62, 60], [-55, 52], [-66, 45], [-76, 35], [-81, 25],
     [-97, 27], [-97, 19], [-87, 15], [-83, 9], [-79, 8], [-92, 15], [-105, 20], [-117, 32], [-124, 40],
     [-125, 49], [-135, 58], [-150, 60], [-165, 60]],
    [[-55, 82], [-25, 82], [-20, 70], [-42, 60], [-52, 65], [-58, 76]],
    [[-80, 8], [-60, 10], [-50, 0], [-35, -6], [-40, -22], [-58, -38], [-68, -55], [-74, -50], [-71, -30],
     [-70, -18], [-81, -5]],
  ],
  europe: [
    [[-10, 36], [-9, 43], [-2, 44], [-5, 48], [2, 51], [8, 54], [5, 58], [5, 62], [15, 69], [28, 71], [40, 67],
     [45, 60], [40, 50], [30, 46], [28, 41], [22, 37], [15, 38], [12, 44], [8, 44], [3, 42], [-2, 37]],
    [[-6, 50], [2, 51], [0, 54], [-3, 58], [-6, 57]],
    [[-24, 66], [-14, 66], [-14, 64], [-22, 63]],
  ],
  middleeast: [
    [[26, 41], [36, 42], [44, 40], [50, 38], [54, 37], [62, 36], [62, 25], [57, 25], [56, 22], [52, 16],
     [44, 12], [43, 17], [38, 22], [35, 28], [34, 31], [36, 34], [30, 36]],
  ],
  asia: [
    [[62, 36], [68, 24], [73, 20], [77, 8], [80, 15], [88, 22], [92, 21], [98, 16], [100, 6], [104, 1],
     [106, 10], [109, 12], [108, 21], [117, 24], [122, 31], [121, 39], [126, 40], [130, 43], [135, 48],
     [141, 53], [120, 50], [100, 50], [88, 48], [80, 45], [70, 40]],
    [[130, 31], [135, 34], [140, 36], [141, 41], [142, 45], [140, 43], [136, 37], [132, 34]],
    [[95, 5], [105, -6], [115, -8], [120, -9], [110, -2], [100, 0]],
    [[109, 1], [117, 7], [119, 1], [116, -4], [110, -3]],
    [[120, 18], [122, 18], [126, 7], [124, 7], [121, 12]],
    [[80, 10], [82, 8], [81, 6], [80, 7]],
  ],
  // not (yet) offered by any of the museums: drawn, but not clickable
  off: [
    [[-17, 21], [-10, 30], [-5, 36], [10, 37], [20, 32], [32, 31], [35, 28], [43, 12], [51, 12], [40, -3],
     [40, -15], [33, -26], [20, -35], [14, -22], [12, -5], [9, 4], [-8, 4], [-17, 14]],
    [[44, -12], [50, -15], [48, -25], [44, -22]],
    [[45, 60], [60, 68], [80, 73], [105, 77], [140, 72], [170, 70], [180, 66], [178, 62], [160, 60],
     [142, 59], [141, 53], [135, 48], [120, 50], [100, 50], [88, 48], [80, 45], [70, 40], [62, 36],
     [54, 37], [50, 38], [44, 40], [45, 48], [40, 50]],
    [[114, -22], [122, -17], [131, -12], [137, -12], [142, -11], [146, -19], [153, -25], [150, -37],
     [141, -38], [131, -31], [115, -34]],
    [[166, -46], [174, -41], [178, -38], [173, -35], [172, -41]],
  ],
};
const MAP_LABEL_AT = { americas: [-95, 38], europe: [14, 52], middleeast: [46, 28], asia: [104, 32] };
const project = ([lon, lat]) => [((lon + 180) / 360) * 1000, ((80 - lat) / 138) * 420];
const toPath = (ring) => "M" + ring.map((p) => project(p).map((v) => v.toFixed(1)).join(",")).join("L") + "Z";

function buildRegionMap() {
  const NS = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const map = $("worldMap");
  map.replaceChildren();
  const grid = svgEl("path", { class: "grid", d: [
    ...[-120, -60, 0, 60, 120].map((lon) => `M${project([lon, 80])[0]},0V420`),
    ...[60, 30, 0, -30].map((lat) => `M0,${project([0, lat])[1]}H1000`),
  ].join("") });
  map.append(grid);

  const offGroup = svgEl("g", { class: "off" });
  for (const ring of MAP_LAND.off) offGroup.append(svgEl("path", { class: "land", d: toPath(ring) }));
  map.append(offGroup);

  const labels = Object.fromEntries((state.options.regions || []).map((r) => [r.key, r.label]));
  for (const key of ["americas", "europe", "middleeast", "asia"]) {
    const g = svgEl("g", { class: "region", "data-region": key, tabindex: "0", role: "button",
                           "aria-label": labels[key] || key });
    for (const ring of MAP_LAND[key]) g.append(svgEl("path", { class: "land", d: toPath(ring) }));
    const [lx, ly] = project(MAP_LABEL_AT[key]);
    const t = svgEl("text", { class: "name", x: lx, y: ly });
    t.textContent = (labels[key] || key).replace(" & Islamic world", "").replace("East & South ", "");
    g.append(t);
    g.addEventListener("click", () => chooseRegion($("region").value === key ? "" : key));
    g.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); chooseRegion(key); }
    });
    g.addEventListener("pointerenter", () => showMapTip(g, key));
    g.addEventListener("pointerleave", () => ($("mapTip").hidden = true));
    map.append(g);
  }

  $("regionList").replaceChildren(
    ...[{ key: "", label: "Everywhere" }, ...(state.options.regions || [])].map((r) =>
      el("button", { type: "button", "data-region": r.key, onclick: () => chooseRegion(r.key) }, r.label)));
  syncRegionUi();
}

function showMapTip(g, key) {
  const n = state.sources.filter((s) => (s.regions || []).includes(key)).length;
  const label = (state.options.regions.find((r) => r.key === key) || {}).label || key;
  const tip = $("mapTip"), wrap = $("worldMap").getBoundingClientRect(), b = g.getBoundingClientRect();
  tip.textContent = `${label} · ${n} museum${n === 1 ? "" : "s"}`;
  tip.style.left = `${b.left - wrap.left + b.width / 2}px`;
  tip.style.top = `${b.top - wrap.top + b.height / 2}px`;
  tip.hidden = false;
}

function chooseRegion(key) {
  $("region").value = key;
  syncRegionUi();
  $("regionDd").open = false;
  scheduleSearch();
}

function syncRegionUi() {
  const key = $("region").value;
  for (const g of document.querySelectorAll("#worldMap .region")) {
    g.classList.toggle("on", g.dataset.region === key);
    g.setAttribute("aria-pressed", String(g.dataset.region === key));
  }
  for (const b of document.querySelectorAll("#regionList button")) {
    b.setAttribute("aria-pressed", String(b.dataset.region === key));
  }
  $("regionSummary").textContent = key
    ? (state.options.regions.find((r) => r.key === key) || {}).label || key : "Everywhere";
}

// ------------------------------------------------------------------ museums
function renderSources() {
  const sorted = [...state.sources].sort((a, b) => a.name.localeCompare(b.name));
  $("sources").replaceChildren(...sorted.map((s) =>
    el("label", { class: "row", title: [s.license, s.supportsColor ? "" : "no colour filter", s.note]
                                         .filter(Boolean).join(" · ") },
      el("input", {
        type: "checkbox", checked: s.enabled,
        onchange: (e) => { s.enabled = e.target.checked; updateSourcesSummary(); scheduleSearch(); },
      }),
      s.note ? el("span", { class: "name" }, s.name, el("em", {}, s.note)) : s.name,
      el("small", {}, s.license))
  ));
  updateSourcesSummary();
}

function updateSourcesSummary() {
  const n = state.sources.filter((s) => s.enabled).length, total = state.sources.length;
  $("sourcesSummary").textContent =
    n === total ? `All ${total} museums` : n === 0 ? "No museums" :
    n === 1 ? state.sources.find((s) => s.enabled).name : `${n} of ${total} museums`;
}

function setAllSources(on) {
  state.sources.forEach((s) => (s.enabled = on));
  renderSources();
  scheduleSearch();
}

// Wait a moment after filter changes, so clicking through options
// doesn't send a burst of searches to the museums.
let searchTimer;
function scheduleSearch() {
  saveSettings();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => search(true), 350);
}

// ------------------------------------------------------------------ search
const activeSources = () => state.sources.filter((s) => s.enabled && state.cursors[s.key] !== 0);
const sourceName = (k) => (state.sources.find((s) => s.key === k) || {}).name || k;

function searchParams() {
  return {
    q: $("q").value.trim(),
    color: $("color").value,
    top: $("topOnly").checked ? "1" : "",
    region: $("region").value,
    subject: $("subject").value,
    period: $("period").value,
    hide: hideValues().join(","),
    minWidth: $("minWidth").value,
    orientation: $("orientation").value,
  };
}

// One request per museum, in parallel: fast museums show up immediately
// instead of waiting for the slowest one.
async function search(reset) {
  if (state.loading && !reset) return;
  const gen = ++state.gen;                       // newer searches make older responses stale
  if (reset) {
    state.results = [];
    state.cursors = {};
    state.errors = {};
    state.skipped = new Set();
    state.showingSelection = false;
    renderTray();
    renderGrid();
  }
  const enabled = activeSources();
  if (!enabled.length) {
    showErrors();
    finishSearch(0, 0);
    return;
  }
  state.loading = true;
  state.pending = new Set(enabled.map((s) => s.key));
  $("loadMore").disabled = true;
  showPending(reset);

  const base = searchParams();
  let added = 0, scanned = 0;
  await Promise.all(enabled.map(async (s) => {
    try {
      const p = new URLSearchParams({ ...base, sources: s.key, cursors: `${s.key}:${state.cursors[s.key] ?? 1}` });
      const data = await api(`/api/search?${p}`);
      if (gen !== state.gen) return;
      const seen = new Set(state.results.map((a) => a.id));
      const fresh = data.results.filter((a) => !seen.has(a.id));
      state.results.push(...fresh);
      appendCards(fresh);
      Object.assign(state.cursors, data.cursors);
      Object.assign(state.errors, data.errors);
      if (!data.errors[s.key]) delete state.errors[s.key];
      (data.skipped || []).forEach((k) => state.skipped.add(k));
      added += fresh.length;
      scanned += data.scanned;
    } catch (e) {
      if (gen === state.gen) state.errors[s.key] = e.message;
    } finally {
      if (gen === state.gen) {
        state.pending.delete(s.key);
        showErrors();
        showPending(reset);
      }
    }
  }));
  if (gen !== state.gen) return;
  state.loading = false;
  finishSearch(added, scanned);
}

function showPending(reset) {
  if (!state.pending.size) return;
  const names = [...state.pending].map(sourceName).join(", ");
  const n = state.results.length;
  setStatus(`${n ? `${n} paintings · ` : ""}${reset && !n ? "Searching" : "Still searching"} ${names}…`);
}

function showErrors() {
  const parts = Object.entries(state.errors).map(([k, e]) =>
    `${sourceName(k)} ${/^(failed|is )/.test(e) ? e : `failed: ${e}`}`);
  const notice = $("notice");
  notice.textContent = parts.join(" · ");
  notice.hidden = !parts.length;
  const skipped = [...state.skipped].map(sourceName);
  $("regionNote").textContent = skipped.length
    ? `Not searched for this region: ${skipped.join(", ")} (little or nothing from there).` : "";
  $("regionNote").hidden = !skipped.length;
}

function finishSearch(added, scanned) {
  const more = activeSources().length > 0;
  $("loadMore").hidden = !more || state.showingSelection;
  $("loadMore").disabled = false;
  const n = state.results.length;
  if (!state.sources.some((s) => s.enabled)) setStatus("Turn on at least one museum.");
  else if (!n) setStatus(more
    ? `Checked ${scanned} paintings, none matched your filters yet. Load more to keep looking, or loosen the filters.`
    : "No paintings found — try loosening the filters.");
  else if (!added && scanned) setStatus(`${n} paintings. Checked ${scanned} more, none matched` +
    (more ? " — keep loading or loosen the filters." : "."));
  else setStatus(`${n} paintings${more ? "" : " — that's everything."}`);
}

function setStatus(t) { $("status").textContent = t; }

// ------------------------------------------------------------------ grid
function card(a) {
  const sel = state.selected.has(a.id);
  return el("article", { class: `card${sel ? " selected" : ""}`, "data-id": a.id },
    el("button", {
      type: "button", class: "thumb", title: "Preview",
      onclick: () => openLightbox(currentList().findIndex((x) => x.id === a.id)),
    }, el("img", { src: img(a.thumbUrl || a.previewUrl), alt: a.title, loading: "lazy", decoding: "async" })),
    ...(state.saved.has(a.id) ? [savedBadge()] : []),
    el("button", { type: "button", class: "icon-btn pick", onclick: () => toggle(a) }),
    el("div", { class: "body" },
      el("h3", { title: a.title }, a.title),
      el("div", { class: "maker" }, [a.maker, a.year].filter(Boolean).join(", ")),
      el("div", { class: "meta" },
        el("span", { class: "badge" }, a.museum),
        el("span", {}, `${a.width} × ${a.height}${a.height > a.width ? " · portrait" : ""}`)),
    ),
  );
}

function withPickState(c, a) {
  const sel = state.selected.has(a.id);
  const label = sel ? "Remove from selection" : "Add to selection";
  c.classList.toggle("selected", sel);
  const b = c.querySelector(".pick");
  b.title = label;
  b.setAttribute("aria-label", label);
  b.setAttribute("aria-pressed", String(sel));
  b.replaceChildren(icon(sel ? "check" : "plus"));
  return c;
}

function savedBadge() {
  return el("span", { class: "saved", title: "Already in your wallpaper collection" }, icon("check"), "Saved");
}

function updateCollectionLink() {
  $("collLink").textContent = state.saved.size ? `My collection (${state.saved.size})` : "My collection";
}

async function refreshSaved() {
  try {
    state.saved = new Set(await api("/api/saved"));
  } catch { return; }
  updateCollectionLink();
  for (const c of $("grid").querySelectorAll(".card")) {
    const has = state.saved.has(c.dataset.id), badge = c.querySelector(".saved");
    if (has && !badge) c.querySelector(".thumb").after(savedBadge());
    if (!has && badge) badge.remove();
  }
}

function renderGrid() {
  $("grid").replaceChildren(...currentList().map((a) => withPickState(card(a), a)));
}

function appendCards(items) {
  if (state.showingSelection || !items.length) return;
  $("grid").append(...items.map((a) => withPickState(card(a), a)));
}

function toggle(a) {
  if (state.selected.has(a.id)) state.selected.delete(a.id);
  else state.selected.set(a.id, a);
  renderTray();
  // update just this card instead of re-rendering (and re-loading) the whole grid
  const c = $("grid").querySelector(`[data-id="${CSS.escape(a.id)}"]`);
  if (c) withPickState(c, a);
  if (state.showingSelection && !state.selected.has(a.id) && c) c.remove();
  if ($("lightbox").open) renderLightbox();
  saveSettings();
}

function renderTray() {
  const n = state.selected.size;
  $("selCount").textContent = `${n} selected`;
  const curator = $("mode").value === "curator";
  $("apply").disabled = n === 0 && !curator;            // the Curator can start from nothing
  $("apply").textContent = curator && n === 0 ? "Start the Curator" : "Set as wallpaper";
  $("showSel").textContent = state.showingSelection ? "back to results" : "show";
}

// ------------------------------------------------------------------ lightbox
function openLightbox(i) {
  state.lbIndex = i;
  renderLightbox();
  if (!$("lightbox").open) $("lightbox").showModal();
}

function renderLightbox() {
  const list = currentList();
  const a = list[state.lbIndex];
  if (!a) return $("lightbox").close();
  // Show the (already cached) thumbnail at once, swap in the sharper image when loaded
  const lb = $("lbImg");
  if (lb.dataset.id !== a.id) {
    lb.dataset.id = a.id;
    lb.src = img(a.thumbUrl || a.previewUrl);
    lb.classList.add("loading");
    loadHighRes(a.id, img(a.previewUrl));
  }
  lb.alt = a.title;
  $("lbTitle").textContent = a.title;
  $("lbMeta").textContent = [a.maker, a.year, a.museum, `${a.width} × ${a.height}`, a.license]
    .filter(Boolean).join(" · ");
  $("lbLink").href = a.link || "#";
  $("lbLink").hidden = !a.link;
  $("lbSelect").textContent = state.selected.has(a.id) ? "✓ Selected" : "Add to selection";
  $("lbSelect").onclick = () => toggle(a);
  $("lbPrev").disabled = state.lbIndex <= 0;
  $("lbNext").disabled = state.lbIndex >= list.length - 1;
}

// Stream the sharper image so the gold bar shows real progress, then swap it in.
let lbAbort = null, lbBlobUrl = null;
async function loadHighRes(id, url) {
  const lb = $("lbImg"), bar = $("lbBar"), fill = $("lbProgress");
  if (lbAbort) lbAbort.abort();
  const ctrl = lbAbort = new AbortController();
  fill.style.transition = "none";
  fill.style.transform = "scaleX(0)";
  void fill.offsetWidth;                         // restart from zero without animating back
  fill.style.transition = "";
  bar.classList.remove("indeterminate");
  bar.classList.add("active");
  const done = () => {
    if (lbAbort !== ctrl) return;
    fill.style.transform = "scaleX(1)";
    setTimeout(() => { if (lbAbort === ctrl) bar.classList.remove("active"); }, 350);
  };
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const total = Number(r.headers.get("Content-Length")) || 0;
    let blob;
    if (r.body && total) {
      const reader = r.body.getReader(), chunks = [];
      let got = 0;
      for (;;) {
        const { done: end, value } = await reader.read();
        if (end) break;
        chunks.push(value);
        got += value.length;
        fill.style.transform = `scaleX(${Math.min(1, got / total)})`;
      }
      blob = new Blob(chunks, { type: r.headers.get("Content-Type") || "image/jpeg" });
    } else {
      bar.classList.add("indeterminate");
      blob = await r.blob();
    }
    if (lb.dataset.id !== id) return;
    if (lbBlobUrl) URL.revokeObjectURL(lbBlobUrl);
    lbBlobUrl = URL.createObjectURL(blob);
    lb.src = lbBlobUrl;
    await lb.decode().catch(() => {});
    lb.classList.remove("loading");
  } catch (e) {
    if (e.name !== "AbortError" && lb.dataset.id === id) lb.classList.remove("loading");
  } finally {
    done();
  }
}

function step(d) {
  const n = state.lbIndex + d;
  if (n >= 0 && n < currentList().length) openLightbox(n);
}

// ------------------------------------------------------------------ interval
function intervalMinutes() {
  if ($("interval").value !== "custom") return Number($("interval").value);
  const n = Math.max(1, Math.round(Number($("customN").value) || 1));
  return Math.min(31 * 1440, n * Number($("customUnit").value));
}

function setIntervalUi(minutes) {
  minutes = Math.max(1, Number(minutes) || 60);
  if (PRESET_INTERVALS.includes(minutes)) {
    $("interval").value = String(minutes);
  } else {
    $("interval").value = "custom";
    const unit = minutes % 1440 === 0 ? 1440 : minutes % 60 === 0 ? 60 : 1;
    $("customUnit").value = String(unit);
    $("customN").value = String(minutes / unit);
  }
  syncModeUi();
}

function intervalText() {
  if ($("interval").value !== "custom") return $("interval").selectedOptions[0].textContent;
  const n = Number($("customN").value) || 1, unit = $("customUnit").selectedOptions[0].textContent;
  return `every ${n} ${n === 1 ? unit.replace(/s$/, "") : unit}`;
}

function syncModeUi() {
  const once = $("mode").value === "once";
  $("intervalWrap").hidden = once;
  $("customWrap").hidden = once || $("interval").value !== "custom";
  $("curatorNote").hidden = $("mode").value !== "curator";
  renderTray();
}

// ------------------------------------------------------------------ apply / restore
async function applySelection() {
  const btn = $("apply");
  btn.disabled = true;
  const curatorMode = $("mode").value === "curator";
  btn.textContent = curatorMode ? "The Curator is choosing…" : `Downloading ${state.selected.size}…`;
  try {
    const r = await api("/api/apply", {
      artworks: [...state.selected.values()],
      label: $("label").checked,
      labelPos: state.labelPos,
      labelStyle: state.labelStyle,
      mode: $("mode").value,
      interval: intervalMinutes(),
    });
    const shown = Object.values(r.wallpapers || {});
    let msg = "";
    if (r.mode === "slideshow") {
      msg = r.slideshow
        ? `Windows slideshow is on: shuffling the paintings in ${r.folder}, ${intervalText()}.`
        : `Couldn't switch on the slideshow automatically. In the Windows settings that opened, choose “Slideshow” and pick ${r.folder}.`;
    } else if (shown.length) {
      msg = `Now showing ${shown.map((t) => `“${t}”`).join(" and ")}.`;
      if (r.mode === "rotate" || r.mode === "curator") msg += ` Next painting ${intervalText()}.`;
    }
    if (r.mode === "curator") {
      const c = r.curator || [];
      msg = (c.length
        ? `The Curator chose ${c.length} new painting${c.length === 1 ? "" : "s"} (${c.map((a) => `“${a.title}”: ${a.reason.toLowerCase()}`).join("; ")}). `
        : "The Curator found nothing new right now and will look again tomorrow. ") + msg;
    }
    msg += ` (${r.downloaded.length} saved`;
    if (r.failed.length) msg += `, ${r.failed.length} failed`;
    if (r.removed.length) msg += `, ${r.removed.length} old removed`;
    msg += ")";
    if (!r.labels && $("label").checked) msg += " Labels skipped: Pillow not installed.";
    toast(msg, 10000);
    renderRotation(r.rotation, r.backup);
    refreshSaved();
  } catch (e) {
    toast(`Couldn't set the wallpaper: ${e.message}`, 10000);
  } finally {
    renderTray();
  }
}

function renderRotation(rot, hasBackup) {
  const on = !!(rot && rot.active);
  $("rotStatus").hidden = $("rotNext").hidden = !on;
  $("restoreBtn").hidden = !(on || hasBackup);
  if (on) {
    $("rotStatus").replaceChildren("Rotation on", ...(rot.nextRun ? [" · next ", el("b", {}, rot.nextRun)] : []));
  }
}

async function restoreWallpaper() {
  const btn = $("restoreBtn");
  btn.disabled = true;
  try {
    const r = await api("/api/rotation", { action: "restore" });
    renderRotation(r.rotation, r.backup);
    toast(r.restored === "previous" ? "Masterpiece stopped. Your previous wallpaper is back."
      : r.restored === "default" ? "Masterpiece stopped. Your earlier wallpaper wasn't saved, so Windows' default is back."
      : "Masterpiece stopped.", 8000);
  } catch (e) {
    toast(`Couldn't restore the wallpaper: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

// ------------------------------------------------------------------ label position
function labelLines(a, mode) {          // mirrors wallpaper.label_lines
  const j = (sep, ...xs) => xs.filter(Boolean).join(sep);
  if (mode === "title") return [a.title];
  if (mode === "artist") return [j(" — ", a.title, a.maker)];
  if (mode === "two") return [a.title, j(" · ", j(", ", a.maker, a.year), a.museum)];
  return [`${a.title} — ${a.maker} · ${a.museum}`];
}

function sampleLabel() {
  const a = state.selected.values().next().value || state.results[0]
    || { title: "Title", maker: "Artist", year: "1880", museum: "Museum" };
  return { lines: labelLines(a, state.labelStyle.text), thumb: a.thumbUrl || a.previewUrl || "" };
}

function syncStyleButtons() {
  for (const seg of document.querySelectorAll("#labelStyles .seg")) {
    for (const b of seg.querySelectorAll("button")) {
      const on = state.labelStyle[seg.dataset.key] === b.dataset.v;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on);
    }
  }
}

function openLabelDialog() {
  syncStyleButtons();
  $("labelDlg").showModal();          // first, so the chips can be measured
  renderLabelStage();
}

function renderLabelStage() {
  const stage = $("labelStage");
  const scr = state.options.screens.length ? state.options.screens
    : [{ x: 0, y: 0, width: 1920, height: 1080, primary: true }];
  const x0 = Math.min(...scr.map((m) => m.x)), y0 = Math.min(...scr.map((m) => m.y));
  const W = Math.max(...scr.map((m) => m.x + m.width)) - x0, H = Math.max(...scr.map((m) => m.y + m.height)) - y0;
  const maxW = Math.min(700, window.innerWidth * 0.86), maxH = Math.min(360, window.innerHeight * 0.5);
  const scale = Math.min(maxW / W, maxH / H);
  stage.style.width = `${W * scale}px`;
  stage.style.height = `${H * scale}px`;
  const sample = sampleLabel();
  const st = state.labelStyle;

  stage.replaceChildren(...scr.map((m) => {
    let fontPx = (Math.min(m.width, m.height) / (LABEL_SIZE_DIV[st.size] || 55)) * scale;
    if (st.look === "subtle") fontPx *= 0.85;
    const chip = el("span", { class: `chip-label look-${st.look} font-${st.font}` },
      ...sample.lines.map((t, i) => el("span", { class: i ? "l2" : "l1" }, t)));
    chip.classList.toggle("two", sample.lines.length > 1);
    chip.style.fontSize = `${Math.max(6, fontPx)}px`;
    const s = el("div", { class: "screen" },
      el("span", { class: "dim" }, `${fmt(m.width, m.height)}${m.primary ? " · main" : ""}`),
      el("span", { class: "guide" }), chip);
    Object.assign(s.style, {
      left: `${(m.x - x0) * scale}px`, top: `${(m.y - y0) * scale}px`,
      width: `${m.width * scale}px`, height: `${m.height * scale}px`,
    });
    if (sample.thumb) s.style.backgroundImage = `url("${img(sample.thumb)}")`;
    return s;
  }));
  placeChips();
}

function placeChips(snapping = false) {
  const { x, y } = state.labelPos;
  const align = x < 0.34 ? "left" : x > 0.66 ? "right" : "center";    // like the real label
  for (const s of $("labelStage").querySelectorAll(".screen")) {
    const chip = s.querySelector(".chip-label");
    // Keep the chip inside the screen, as the real label is
    const sw = s.clientWidth, sh = s.clientHeight, cw = chip.offsetWidth, ch = chip.offsetHeight;
    const m = parseFloat(chip.style.fontSize) || 8;
    const cx = Math.min(Math.max(x * sw, m + cw / 2), sw - m - cw / 2);
    const cy = Math.min(Math.max(y * sh, m + ch / 2), sh - m - ch / 2);
    chip.style.left = `${cx}px`;
    chip.style.top = `${cy}px`;
    chip.style.textAlign = align;
    s.classList.toggle("snap", snapping);
  }
}

function setupLabelDrag() {
  const stage = $("labelStage");
  let dragging = null;
  const move = (e) => {
    if (!dragging) return;
    const r = dragging.getBoundingClientRect();
    let x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    x = Math.min(1, Math.max(0, x));
    y = Math.min(1, Math.max(0, y));
    const snap = Math.abs(x - 0.5) < 0.025;        // gentle snap to the vertical centre line
    if (snap) x = 0.5;
    state.labelPos = { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 };
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
  const end = () => {
    if (!dragging) return;
    dragging = null;
    stage.classList.remove("dragging");
    placeChips(false);
    saveSettings();
  };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);
  for (const b of document.querySelectorAll(".presets [data-pos]")) {
    b.addEventListener("click", () => {
      const [x, y] = b.dataset.pos.split(",").map(Number);
      state.labelPos = { x, y };
      placeChips();
      saveSettings();
    });
  }
  for (const seg of document.querySelectorAll("#labelStyles .seg")) {
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-v]");
      if (!b) return;
      state.labelStyle = { ...state.labelStyle, [seg.dataset.key]: b.dataset.v };
      syncStyleButtons();
      renderLabelStage();
      saveSettings();
    });
  }
  $("labelDone").addEventListener("click", () => {
    $("labelDlg").close();
    if ($("label").checked) applyLabelNow();
    else saveSettings();
  });
}

// ------------------------------------------------------------------ updates
let updateInfo = null, updateTimer;

function renderWhatsNew(w) {
  $("whatsNew").hidden = !w;
  if (!w) return;
  $("whatsNewTitle").textContent = `Masterpiece is updated to ${w.version}.`;
  $("whatsNewNotes").textContent = w.notes || "";
  $("whatsNewNotes").hidden = !w.notes;
  $("whatsNewPage").hidden = !w.page;
}

function renderUpdate(u) {
  updateInfo = u;
  clearTimeout(updateTimer);
  renderWhatsNew(u.whatsNew);
  const ver = $("verBtn");
  ver.textContent = u.available ? `v${u.current} · update ${u.latest} available` : `v${u.current}`;
  ver.classList.toggle("new", !!u.available);
  const p = u.progress || {};
  const busy = p.state === "downloading" || p.state === "installing";
  const show = u.available && (busy || p.state === "error" || u.skipped !== u.latest);
  $("updateBar").hidden = !show;
  if (!show) return;

  const pct = p.total ? Math.min(100, Math.round((p.done * 100) / p.total)) : 0;
  let text;
  if (p.state === "downloading") text = [`Downloading Masterpiece ${u.latest}… ${pct ? `${pct}%` : ""}`];
  else if (p.state === "installing") text = [`Installing Masterpiece ${u.latest}. It restarts in a moment.`];
  else if (p.state === "error") text = [`The update didn't work: ${p.error}`];
  else text = [el("b", {}, `Masterpiece ${u.latest}`), ` is available. You have ${u.current}.`];
  if (!u.canInstall && !busy) text.push(" (Running from source: update with git pull.)");
  $("updateText").replaceChildren(...text);
  $("updateInstall").hidden = busy || !u.canInstall;
  $("updateInstall").textContent = p.state === "error" ? "Try again" : "Install now";
  $("updateLater").hidden = busy;
  $("updateNotes").hidden = !(u.release && u.release.page);

  const bar = $("updateBarProgress");
  bar.hidden = !busy;
  bar.classList.toggle("active", busy);
  bar.classList.toggle("indeterminate", p.state === "installing" || (busy && !p.total));
  $("updateProgress").style.transform = `scaleX(${pct / 100})`;
  if (busy) updateTimer = setTimeout(() => api("/api/update").then(renderUpdate).catch(() => {}), 700);
}

function setupUpdates() {
  api("/api/update").then(renderUpdate).catch(() => {});
  $("verBtn").addEventListener("click", async () => {
    try {
      const u = await api("/api/update", { action: "check" });
      if (u.available) renderUpdate({ ...u, skipped: "" });       // asked explicitly: show it again
      else {
        renderUpdate(u);
        toast(!u.enabled ? "Update checks aren't set up in this copy of Masterpiece."
          : u.error || `You have the newest version (${u.current}).`);
      }
    } catch (e) { toast(`Couldn't check for updates: ${e.message}`); }
  });
  $("updateInstall").addEventListener("click", async () => {
    try { renderUpdate(await api("/api/update", { action: "install" })); }
    catch (e) { toast(`Couldn't start the update: ${e.message}`); }
  });
  $("updateLater").addEventListener("click", async () => {
    try {
      renderUpdate(await api("/api/update", { action: "skip", version: updateInfo.latest }));
      toast("OK. Install it later via the version number at the top, or the tray menu.");
    } catch (e) { toast(e.message); }
  });
  $("updateNotes").addEventListener("click", () => window.open(updateInfo.release.page, "_blank", "noopener"));
  $("whatsNewOk").addEventListener("click", () => {
    renderWhatsNew(null);
    api("/api/update", { action: "seenWhatsNew" }).catch(() => {});
  });
  $("whatsNewPage").addEventListener("click", () => {
    const w = updateInfo && updateInfo.whatsNew;
    if (w && w.page) window.open(w.page, "_blank", "noopener");
  });
}

// ------------------------------------------------------------------ init
async function init() {
  const [sources, options, s] = await Promise.all([
    api("/api/sources"), api("/api/options"), api("/api/settings"),
  ]);
  if (!s.introSeen) {                 // first visit: explain how it works
    location.replace("guide.html");
    return;
  }
  state.options = options;
  state.sources = sources.map((src) => ({ ...src, enabled: s.enabledSources.includes(src.key) }));
  for (const a of s.selection || []) state.selected.set(a.id, a);
  if (s.labelPos && typeof s.labelPos.x === "number") state.labelPos = s.labelPos;
  if (s.labelStyle && typeof s.labelStyle === "object") state.labelStyle = { ...state.labelStyle, ...s.labelStyle };

  renderOptions(s);
  $("q").value = s.query || "";
  $("color").value = s.color || "";
  $("topOnly").checked = !!s.topOnly;
  $("region").value = s.region || "";
  $("subject").value = s.subject || "";
  $("period").value = s.period || "";
  $("minWidth").value = String(s.minWidth ?? "sharp");
  if (!$("minWidth").value) $("minWidth").value = "sharp";      // option no longer exists
  $("orientation").value = s.orientation || "screens";
  if ($("orientation").value === "span" && options.screens.length < 2) $("orientation").value = "screens";
  $("label").checked = !!s.label;
  $("mode").value = ["slideshow", "rotate", "curator", "once"].includes(s.mode) ? s.mode : "rotate";
  setIntervalUi(s.interval || 60);
  api("/api/rotation").then((r) => renderRotation(r, r.backup)).catch(() => {});
  try { state.saved = new Set(await api("/api/saved")); } catch { /* badges are optional */ }
  updateCollectionLink();

  renderSources();
  renderTray();
  setupLabelDrag();
  buildRegionMap();
  setupUpdates();
  if (new URLSearchParams(location.search).has("label")) {       // from Settings: "Style & position…"
    history.replaceState(null, "", "/");
    openLabelDialog();
  }

  $("search").addEventListener("submit", (e) => { e.preventDefault(); saveSettings(); search(true); });
  $("srcAll").addEventListener("click", () => setAllSources(true));
  $("srcNone").addEventListener("click", () => setAllSources(false));
  document.addEventListener("click", (e) => {      // close the dropdowns when clicking elsewhere
    for (const id of ["sourcesDd", "regionDd"]) if (!$(id).contains(e.target)) $(id).open = false;
  });
  for (const id of ["color", "topOnly", "minWidth", "orientation", "region", "subject", "period"]) {
    $(id).addEventListener("change", scheduleSearch);
  }
  $("hide").addEventListener("change", scheduleSearch);
  for (const id of ["mode", "interval", "customN", "customUnit"]) {
    $(id).addEventListener("change", saveSettings);
  }
  $("label").addEventListener("change", applyLabelNow);      // label on/off shows right away
  $("mode").addEventListener("change", syncModeUi);
  $("interval").addEventListener("change", () => {
    syncModeUi();
    if ($("interval").value === "custom") $("customN").focus();
  });
  $("labelPosBtn").addEventListener("click", openLabelDialog);
  $("rotNext").addEventListener("click", async () => {
    try {
      const r = await api("/api/rotation", { action: "next" });
      toast(`Now showing ${Object.values(r.wallpapers).map((t) => `“${t}”`).join(" and ")}.`);
      renderRotation(r.rotation, r.backup);
    } catch (e) { toast(`Couldn't change the wallpaper: ${e.message}`); }
  });
  $("restoreBtn").addEventListener("click", restoreWallpaper);
  $("loadMore").addEventListener("click", () => search(false));
  $("apply").addEventListener("click", applySelection);
  $("clearSel").addEventListener("click", () => {
    state.selected.clear();
    state.showingSelection = false;
    renderTray(); renderGrid(); saveSettings();
  });
  $("showSel").addEventListener("click", () => {
    state.showingSelection = !state.showingSelection;
    renderTray(); renderGrid();
    $("loadMore").hidden = state.showingSelection || !activeSources().length;
  });
  $("lbClose").addEventListener("click", () => $("lightbox").close());
  $("lightbox").addEventListener("close", () => {     // stop downloading when the preview closes
    if (lbAbort) lbAbort.abort();
    $("lbBar").classList.remove("active");
    delete $("lbImg").dataset.id;
  });
  $("lbPrev").addEventListener("click", () => step(-1));
  $("lbNext").addEventListener("click", () => step(1));
  $("lightbox").addEventListener("click", (e) => { if (e.target === $("lightbox")) $("lightbox").close(); });
  document.addEventListener("keydown", (e) => {
    if (!$("lightbox").open) return;
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  });

  search(true);
}

init().catch((e) => setStatus(`Could not start: ${e.message}`));
