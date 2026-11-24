"use strict";
// Search art: filters in the side panel, results grid, preview, and the selection bar.

const state = {
  sources: [],
  options: { subjects: [], periods: [], regions: [], hide: [], screens: [], span: null },
  results: [],
  cursors: {},             // source key -> next page (0 = nothing more)
  selected: new Map(),     // id -> artwork
  showingSelection: false,
  loading: false,
  saved: new Set(),        // ids already in the collection
  gen: 0,                  // search generation, to drop stale responses
  pending: new Set(),      // museums still answering
  errors: {},
  skipped: new Set(),      // museums without works from the chosen regions
  regions: new Set(),      // chosen regions (empty = everywhere); several at once is fine
  lbIndex: -1,
};

const hideValues = () => [...document.querySelectorAll("#hide input:checked")].map((i) => i.value);

let saveTimer;
function saveSettings() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api("/api/settings", {
    enabledSources: state.sources.filter((s) => s.enabled).map((s) => s.key),
    query: $("q").value.trim(),
    color: $("color").value,
    topOnly: $("topOnly").checked,
    region: regionValue(),
    subject: $("subject").value,
    period: $("period").value,
    hide: hideValues(),
    minWidth: $("minWidth").value,
    orientation: $("orientation").value,
    selection: [...state.selected.values()],
  }).catch((e) => toast(`Could not save settings: ${e.message}`)), 400);
}

function currentList() {
  return state.showingSelection ? [...state.selected.values()] : state.results;
}

// ------------------------------------------------------------------ options
function renderOptions(s) {
  const o = state.options;
  for (const x of o.subjects) $("subject").append(el("option", { value: x.key }, x.label));
  for (const x of o.periods) $("period").append(el("option", { value: x.key }, x.label));
  $("hide").replaceChildren(...o.hide.map((x) => el("label", { class: "check" },
    el("input", { type: "checkbox", value: x.key, checked: (s.hide || []).includes(x.key) }), x.label)));
  updateHideSummary();
  const scr = o.screens;
  if (scr.length) {
    $("screenInfo").textContent = `Your screen${scr.length > 1 ? "s" : ""}: ` +
      scr.map((m) => `${fmt(m.width, m.height)}${m.height > m.width ? " portrait" : ""}`).join(" · ");
    $("optSharp").textContent = `Sharp on my screen${scr.length > 1 ? "s" : ""}`;
    if (o.span) $("optSpan").textContent = `Spans all my screens (${fmt(o.span.width, o.span.height)})`;
  } else {
    $("screenInfo").textContent = "Screen size unknown, assuming 1920×1080.";
  }
  const multi = scr.length > 1;
  $("optSpan").hidden = !multi;
  $("optSpan").disabled = !multi;
}

function updateHideSummary() {
  const n = hideValues().length;
  $("hideSummary").textContent = n ? `${n} hidden` : "";
}

// ------------------------------------------------------------------ region map
// Simplified continents as [longitude, latitude] outlines, drawn equirectangular.
const MAP_LAND = {
  americas: [
    [[-168, 66], [-140, 70], [-95, 72], [-80, 63], [-62, 60], [-55, 52], [-66, 45], [-76, 35], [-81, 25],
     [-97, 26], [-106, 31], [-117, 32], [-124, 40], [-125, 49], [-135, 58], [-150, 60], [-165, 60]],
    [[-55, 82], [-25, 82], [-20, 70], [-42, 60], [-52, 65], [-58, 76]],
  ],
  latam: [
    [[-97, 26], [-97, 19], [-87, 15], [-83, 9], [-79, 8], [-92, 15], [-105, 20], [-117, 32], [-106, 31]],
    [[-80, 8], [-60, 10], [-50, 0], [-35, -6], [-40, -22], [-58, -38], [-68, -55], [-74, -50], [-71, -30],
     [-70, -18], [-81, -5]],
  ],
  oceania: [
    [[114, -22], [122, -17], [131, -12], [137, -12], [142, -11], [146, -19], [153, -25], [150, -37],
     [141, -38], [131, -31], [115, -34]],
    [[166, -46], [174, -41], [178, -38], [173, -35], [172, -41]],
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
  africa: [
    [[-17, 21], [-10, 30], [-5, 36], [10, 37], [20, 32], [32, 31], [35, 28], [43, 12], [51, 12], [40, -3],
     [40, -15], [33, -26], [20, -35], [14, -22], [12, -5], [9, 4], [-8, 4], [-17, 14]],
    [[44, -12], [50, -15], [48, -25], [44, -22]],
  ],
  russia: [
    [[45, 60], [60, 68], [80, 73], [105, 77], [140, 72], [170, 70], [180, 66], [178, 62], [160, 60],
     [142, 59], [141, 53], [135, 48], [120, 50], [100, 50], [88, 48], [80, 45], [70, 40], [62, 36],
     [54, 37], [50, 38], [44, 40], [45, 48], [40, 50]],
  ],
  off: [],      // land no source offers yet: drawn, but not clickable
};
const MAP_LABEL_AT = { americas: [-100, 45], latam: [-60, -12], europe: [14, 52], middleeast: [46, 28],
                       asia: [104, 32], oceania: [134, -26], africa: [20, 5], russia: [100, 62] };
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
  for (const key of ["americas", "latam", "europe", "russia", "middleeast", "africa", "asia", "oceania"]) {
    const g = svgEl("g", { class: "region", "data-region": key, tabindex: "0", role: "button",
                           "aria-label": labels[key] || key });
    for (const ring of MAP_LAND[key]) g.append(svgEl("path", { class: "land", d: toPath(ring) }));
    const [lx, ly] = project(MAP_LABEL_AT[key]);
    const t = svgEl("text", { class: "name", x: lx, y: ly });
    t.textContent = (labels[key] || key).replace(" & Islamic world", "").replace("East & South ", "");
    g.append(t);
    g.addEventListener("click", () => toggleRegion(key));
    g.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleRegion(key); }
    });
    g.addEventListener("pointerenter", () => showMapTip(g, key));
    g.addEventListener("pointerleave", () => ($("mapTip").hidden = true));
    map.append(g);
  }

  $("mapClear").onclick = () => toggleRegion("");
  syncRegionUi();
}

function showMapTip(g, key) {
  const n = state.sources.filter((s) => (s.regions || []).includes(key)).length;
  const label = (state.options.regions.find((r) => r.key === key) || {}).label || key;
  const tip = $("mapTip"), wrap = $("worldMap").getBoundingClientRect(), b = g.getBoundingClientRect();
  tip.textContent = `${label} · ${n} museum${n === 1 ? "" : "s"}`;
  tip.hidden = false;
  // keep the whole label inside the map
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  const x = Math.min(Math.max(b.left - wrap.left + b.width / 2 - tw / 2, 4), wrap.width - tw - 4);
  const y = Math.min(Math.max(b.top - wrap.top + b.height / 2 - th - 6, 4), wrap.height - th - 4);
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

const regionValue = () => [...state.regions].sort().join(",");

// Click a continent to add it, click again to remove it; "Everywhere" clears them all.
function toggleRegion(key) {
  if (!key) state.regions.clear();
  else if (state.regions.has(key)) state.regions.delete(key);
  else state.regions.add(key);
  if (state.regions.size === (state.options.regions || []).length) state.regions.clear();   // all = everywhere
  syncRegionUi();
  scheduleSearch();
}

function syncRegionUi() {
  const on = state.regions;
  for (const g of document.querySelectorAll("#worldMap .region")) {
    g.classList.toggle("on", on.has(g.dataset.region));
    g.setAttribute("aria-pressed", String(on.has(g.dataset.region)));
  }
  $("mapClear").hidden = !on.size;
  const labels = (state.options.regions || []).filter((r) => on.has(r.key)).map((r) => r.label.split(" & ")[0]);
  $("regionSummary").textContent = !on.size ? "Everywhere" : on.size === 1 ? labels[0] : `${on.size} regions`;
}

// ------------------------------------------------------------------ museums
function renderSources() {
  const sorted = [...state.sources].sort((a, b) => a.name.localeCompare(b.name));
  $("sources").replaceChildren(...sorted.map((s) =>
    el("label", { class: "check", title: s.license || "" },
      el("input", {
        type: "checkbox", checked: s.enabled,
        onchange: (e) => { s.enabled = e.target.checked; updateSourcesSummary(); scheduleSearch(); },
      }),
      el("span", { class: "name" }, s.name))));
  updateSourcesSummary();
}

function updateSourcesSummary() {
  const n = state.sources.filter((s) => s.enabled).length, total = state.sources.length;
  $("sourcesSummary").textContent = n === total ? `all ${total}` : `${n} of ${total}`;
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
    region: regionValue(),
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
    `${sourceName(k)} ${/^(failed|is |isn't )/.test(e) ? e : `failed: ${e}`}`);
  const notice = $("notice");
  notice.textContent = parts.join(" · ");
  // only "not available right now": a calm grey note, not a red error
  notice.classList.toggle("soft", Object.values(state.errors).every((e) => /^isn't available/.test(e)));
  notice.hidden = !parts.length;
  // say which museums have paintings from the chosen regions (short), not which ones don't
  const searched = state.sources.filter((s) => s.enabled && !state.skipped.has(s.key)).map((s) => s.name);
  $("regionNote").textContent = state.skipped.size
    ? `From ${state.regions.size > 1 ? "these regions" : "here"}: ${searched.join(", ") || "none of the chosen museums"}` : "";
  $("regionNote").hidden = !state.skipped.size;
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
// Wikimedia makes rarely viewed thumbnails on request and allows about one a second, so its
// pictures load through a small queue of their own (only the ones near the screen): they never
// hold up the other museums' pictures, which load as usual.
const SLOW_HOSTS = /^https:\/\/upload\.wikimedia\.org\//;
const slowQueue = [];
let slowBusy = 0;
const slowSeen = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    slowSeen.unobserve(e.target);
    slowQueue.push(e.target);
  }
  pumpSlow();
}, { rootMargin: "400px" });

function pumpSlow() {
  while (slowBusy < 2 && slowQueue.length) {
    const im = slowQueue.shift();
    if (!im.isConnected) continue;
    slowBusy++;
    const done = () => { slowBusy--; pumpSlow(); };
    im.addEventListener("load", done, { once: true });
    im.addEventListener("error", done, { once: true });
    im.src = im.dataset.src;
  }
}

function thumbImg(a) {
  const url = a.thumbUrl || a.previewUrl;
  const im = el("img", { alt: a.title, decoding: "async", onerror: retryImage, "data-retry-able": "" });
  if (SLOW_HOSTS.test(url)) { im.dataset.src = img(url); slowSeen.observe(im); }
  else { im.loading = "lazy"; im.src = img(url); }
  return im;
}

function card(a) {
  const sel = state.selected.has(a.id);
  return el("article", { class: `card${sel ? " selected" : ""}`, "data-id": a.id },
    el("button", {
      type: "button", class: "thumb", title: "Preview",
      onclick: () => openLightbox(currentList().findIndex((x) => x.id === a.id)),
    }, thumbImg(a)),
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


function savedBadge() {
  return el("span", { class: "saved", title: "Already in your collection" }, icon("check"), "Saved");
}

async function refreshSaved() {
  try { state.saved = new Set(await api("/api/saved")); } catch { return; }
  setCollectionCount(state.saved.size);
  for (const c of $("grid").querySelectorAll(".card")) {
    const has = state.saved.has(c.dataset.id), badge = c.querySelector(".saved");
    if (has && !badge) c.querySelector(".thumb").after(savedBadge());
    if (!has && badge) badge.remove();
  }
}

// ------------------------------------------------------------------ selection bar
function renderTray() {
  const n = state.selected.size;
  $("selbar").hidden = n === 0;
  document.body.classList.toggle("has-selbar", n > 0);
  $("selCount").textContent = `${n} selected`;
  $("showSel").textContent = state.showingSelection ? "back to results" : "show";
}

async function addSelection() {
  const btn = $("addSel");
  const arts = [...state.selected.values()];
  btn.disabled = true;
  btn.textContent = `Adding ${arts.length}…`;
  try {
    const r = await api("/api/collection", { action: "add", artworks: arts });
    if (r.failed.length) toast(`${r.failed.length} couldn't be downloaded.`, 8000);
    state.selected.clear();
    state.showingSelection = false;
    renderTray();
    renderGrid();
    refreshSaved();
  } catch (e) {
    toast(`Couldn't add them: ${e.message}`, 8000);
  } finally {
    btn.disabled = false;
    btn.textContent = "Add to collection";
  }
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

// A picture the museum wouldn't send yet (it asked us to slow down) tries again later, twice.
function retryImage(e) {
  const im = e.target, n = Number(im.dataset.retry || 0);
  if (n >= 2) return;
  im.dataset.retry = String(n + 1);
  const src = im.src.replace(/&r=\d+$/, "");
  setTimeout(() => { if (im.isConnected) im.src = `${src}&r=${n + 1}`; }, n ? 60000 : 25000);
}

// ------------------------------------------------------------------ init
async function init() {
  mountShell("search");
  setupPanel("search");
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

  renderOptions(s);
  $("q").value = s.query || "";
  $("color").value = s.color || "";
  $("topOnly").checked = !!s.topOnly;
  state.regions = new Set(String(s.region || "").split(",").filter(Boolean));
  $("subject").value = s.subject || "";
  $("period").value = s.period || "";
  $("minWidth").value = String(s.minWidth ?? "sharp");
  if (!$("minWidth").value) $("minWidth").value = "sharp";
  $("orientation").value = s.orientation || "screens";
  if ($("orientation").value === "span" && options.screens.length < 2) $("orientation").value = "screens";
  try { state.saved = new Set(await api("/api/saved")); } catch { /* badges are optional */ }

  renderSources();
  renderTray();
  buildRegionMap();

  $("search").addEventListener("submit", (e) => { e.preventDefault(); saveSettings(); search(true); });
  $("q").addEventListener("search", () => { if (!$("q").value) scheduleSearch(); });   // the x in the box
  $("srcAll").addEventListener("click", () => setAllSources(true));
  $("srcNone").addEventListener("click", () => setAllSources(false));
  for (const id of ["color", "topOnly", "minWidth", "orientation", "subject", "period"]) {
    $(id).addEventListener("change", scheduleSearch);
  }
  $("hide").addEventListener("change", () => { updateHideSummary(); scheduleSearch(); });
  $("loadMore").addEventListener("click", () => search(false));
  $("addSel").addEventListener("click", addSelection);
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
  maybeStartTour(s);
}

init().catch((e) => setStatus(`Could not start: ${e.message}`));
