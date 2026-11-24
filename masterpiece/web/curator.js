"use strict";
// The Curator tab: what's on your desktop (desk.js), how it changes, and your taste.

const cur = { s: {}, rot: {}, options: {}, sources: [], items: [], group: "subjects" };
const PRESET_INTERVALS = [10, 30, 60, 180, 1440];
const LEVELS = ["Never", "Less", "Normal", "More", "A lot"];
const SURPRISE = ["Never", "Rarely", "Sometimes", "Often", "Very often"];
const thumbUrl = (name, large) => `/api/thumb?name=${encodeURIComponent(name)}${large ? "&size=large" : ""}`;

async function saveSettings(updates) {
  try {
    cur.s = await api("/api/settings", updates);
  } catch (e) { toast(`Couldn't save: ${e.message}`); }
}

// ------------------------------------------------------------------ now on your screens
function renderNow() {
  renderDesk();
  renderUpcoming();
  renderAskBtn();
}

// "Ask the Curator now" shows that it is busy, also when you come back to this tab
let asking = false;
function renderAskBtn() {
  const busy = asking || !!cur.rot.curatorBusy;
  $("askBtn").disabled = busy;
  $("askBtn").textContent = busy ? "The Curator is looking…" : "Ask the Curator now";
  clearTimeout(renderAskBtn.timer);
  if (cur.rot.curatorBusy && !asking) {
    renderAskBtn.timer = setTimeout(() => api("/api/rotation").then(setRotation).catch(() => {}), 4000);
  }
}

async function rotation(action, extra = {}, msg) {
  try {
    const r = await api("/api/rotation", { action, ...extra });
    if (r.curator && r.curator.length) await loadItems();
    setRotation(r);
    if (typeof msg === "function") msg = msg(r);
    if (msg) toast(msg, 8000);
    return r;
  } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ how it changes
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
  $("customWrap").hidden = $("interval").value !== "custom";
}

function renderSource() {
  for (const b of $("sourcePick").children) {
    const on = b.dataset.mode === cur.s.mode;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  }
  $("tasteBox").classList.toggle("dim", cur.s.mode !== "curator");
  $("tasteNote").textContent = cur.s.mode === "curator"
    ? "The Curator looks for paintings like these. Slide to “never” to leave something out."
    : "Used when the Curator chooses. Switch “What to show” to “Curator chooses” to use it.";
}

async function refreshLabel() {
  try {
    await api("/api/rotation", { action: "refresh" });
    setRotation(await api("/api/rotation"));
  } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ your taste
function groupItems(group) {
  const o = cur.options;
  if (group === "subjects") return o.subjects.map((x) => [x.key, x.label]);
  if (group === "periods") return o.periods.map((x) => [x.key, x.label]);
  if (group === "regions") return o.regions.map((x) => [x.key, x.label]);
  return [...cur.sources].sort((a, b) => a.name.localeCompare(b.name)).map((x) => [x.key, x.name]);
}

function level(group, key) {
  const v = ((cur.s.curatorTaste || {})[group] || {})[key];
  return Number.isInteger(v) ? v : 2;
}

let tasteTimer;
function saveTaste() {
  clearTimeout(tasteTimer);
  tasteTimer = setTimeout(() => saveSettings({ curatorTaste: cur.s.curatorTaste }), 400);
}

function renderSliders() {
  for (const b of $("tasteTabs").children) b.classList.toggle("on", b.dataset.group === cur.group);
  const group = cur.group;
  $("sliders").replaceChildren(...groupItems(group).map(([key, label]) => {
    const val = el("span", { class: "s-val" }, LEVELS[level(group, key)]);
    const input = el("input", { type: "range", min: "0", max: "4", step: "1", value: String(level(group, key)),
      "aria-label": label });
    const row = el("div", { class: `slider-row lv${level(group, key)}` }, el("span", { class: "s-label" }, label), input, val);
    input.addEventListener("input", () => {
      const v = Number(input.value);
      cur.s.curatorTaste = cur.s.curatorTaste || {};
      cur.s.curatorTaste[group] = { ...(cur.s.curatorTaste[group] || {}), [key]: v };
      val.textContent = LEVELS[v];
      row.className = `slider-row lv${v}`;
      saveTaste();
    });
    return row;
  }));
}

function renderArtists() {
  const fav = new Set((cur.s.favourites || []));
  const counts = new Map();
  for (const it of cur.items) {
    const m = (it.maker || "").trim();
    if (!m || /unknown|anonym|ubekendt|onbekend|unbekannt|inconnu|sconosciuto|desconocido/i.test(m)) continue;
    counts.set(m, (counts.get(m) || 0) + (fav.has(it.id) ? 3 : 1));
  }
  const muted = new Set(cur.s.curatorMutedArtists || []);
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 14);
  $("artists").replaceChildren(...(top.length ? top.map(([m]) => el("button", {
    type: "button", class: muted.has(m) ? "muted" : "", "aria-pressed": String(!muted.has(m)),
    title: muted.has(m) ? "Left out: click to include again" : "Click to leave this artist out",
    onclick: () => {
      const set = new Set(cur.s.curatorMutedArtists || []);
      set.has(m) ? set.delete(m) : set.add(m);
      saveSettings({ curatorMutedArtists: [...set] }).then(renderArtists);
    } }, m)) : [el("span", { class: "muted" }, "Add or favourite a few paintings and your artists appear here.")]));
}

function renderRecent() {
  const latest = cur.rot.curatorLatest || [];
  $("recentBox").hidden = !latest.length;
  $("recent").replaceChildren(...latest.map((a) => el("a", { class: "recent-item", href: `painting.html?name=${encodeURIComponent(a.name)}` },
    el("img", { src: thumbUrl(a.name), alt: a.title, loading: "lazy" }),
    el("div", {}, el("b", {}, a.title), el("span", {}, a.maker), el("span", { class: "now-reason" }, icon("sparkle"), a.reason)))));
}

// ------------------------------------------------------------------ init
async function loadItems() {
  const d = await api("/api/collection");
  cur.items = d.items;
  setCollectionCount(d.items.length);
}

async function init() {
  mountShell("curator");
  const [s, rot, options, sources] = await Promise.all([
    api("/api/settings"), api("/api/rotation"), api("/api/options"), api("/api/sources")]);
  Object.assign(cur, { s, rot, options, sources });
  await loadItems();

  setIntervalUi(s.interval || 60);
  setupDesk();
  $("timeOfDay").checked = !!s.timeOfDay;
  $("seasons").checked = !!s.seasons;
  $("lockScreen").checked = !!s.lockScreen;
  $("curatorDaily").value = String([1, 2, 3, 5].includes(s.curatorDaily) ? s.curatorDaily : 3);
  $("surprise").value = String(Number.isInteger(s.curatorSurprise) ? s.curatorSurprise : 2);
  $("surpriseVal").textContent = SURPRISE[Number($("surprise").value)];
  renderNow();
  renderSource();
  renderSliders();
  renderArtists();
  renderRecent();

  // controls
  document.addEventListener("rotation", async (e) => {
    const was = cur.rot.curatorBusy;
    cur.rot = e.detail;
    if (cur.rot.mode && cur.rot.mode !== cur.s.mode) { cur.s.mode = cur.rot.mode; renderSource(); }
    if (was && !cur.rot.curatorBusy) await loadItems();     // the Curator just finished
    renderNow();
    renderRecent();
  });

  $("sourcePick").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b || b.dataset.mode === cur.s.mode) return;
    cur.rot = await api("/api/rotation", { action: "source", mode: b.dataset.mode });
    cur.s.mode = cur.rot.mode;
    renderSource();
    renderNow();
  });
  const onInterval = () => {
    $("customWrap").hidden = $("interval").value !== "custom";
    rotation("interval", { interval: intervalMinutes() });
  };
  $("interval").addEventListener("change", () => {
    if ($("interval").value === "custom") { $("customWrap").hidden = false; $("customN").focus(); return; }
    onInterval();
  });
  $("customN").addEventListener("change", onInterval);
  $("customUnit").addEventListener("change", onInterval);
  $("timeOfDay").addEventListener("change", (e) => saveSettings({ timeOfDay: e.target.checked }));
  $("seasons").addEventListener("change", (e) => saveSettings({ seasons: e.target.checked }));
  $("lockScreen").addEventListener("change", async (e) => {
    e.target.disabled = true;
    try {
      await api("/api/system", { action: "lockScreen", on: e.target.checked });
      cur.s.lockScreen = e.target.checked;
    } catch (err) { toast(`Didn't work: ${err.message}`); e.target.checked = !e.target.checked; }
    e.target.disabled = false;
  });

  // taste
  $("tasteTabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-group]");
    if (!b) return;
    cur.group = b.dataset.group;
    renderSliders();
  });
  $("surprise").addEventListener("input", () => {
    $("surpriseVal").textContent = SURPRISE[Number($("surprise").value)];
    clearTimeout(tasteTimer);
    tasteTimer = setTimeout(() => saveSettings({ curatorSurprise: Number($("surprise").value) }), 400);
  });
  $("curatorDaily").addEventListener("change", () => saveSettings({ curatorDaily: Number($("curatorDaily").value) }));
  $("askBtn").addEventListener("click", async () => {
    asking = true;
    renderAskBtn();
    await rotation("curator", {}, (r) => ((r.curator || []).length ? ""
      : "The Curator found nothing new right now. Try again later or loosen your taste a little."));
    asking = false;
    renderAskBtn();
  });
}

init().catch((e) => toast(`Couldn't load the Curator: ${e.message}`));
