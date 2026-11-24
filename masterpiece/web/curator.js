"use strict";
// The Curator tab: what's on your screens (with ♥ and thumbs), what comes next, how it changes,
// and what the Curator looks for. The preview with layout and label is on Settings (desk.js).

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
// One tile per screen (the same painting on several screens: one tile), in screen order
function renderOnScreens() {
  const mons = cur.rot.screens || [];
  const byKey = new Map(mons.map((m) => [m.id, m]));
  const seen = new Map();
  for (const c of cur.rot.onScreens || []) {
    const m = byKey.get(c.key);
    if (seen.has(c.name)) { seen.get(c.name).mons.push(m); continue; }
    seen.set(c.name, { c, mons: [m] });
  }
  const tiles = [...seen.values()].sort((a, b) => ((a.mons[0] || {}).x || 0) - ((b.mons[0] || {}).x || 0));
  if (!tiles.length) {
    $("nowAbout").hidden = true;
    $("nowRow").replaceChildren(el("p", { class: "muted" },
      cur.rot.count ? "Nothing from Masterpiece on your screens yet. Press › in the bar below." : "Your collection is still empty."));
    return;
  }
  const crop = cur.s.crop || "middle";
  $("nowAbout").hidden = false;
  if (!cur.sel || !tiles.some((t) => t.c.name === cur.sel) && !cur.selPinned) cur.sel = tiles[0].c.name;
  $("nowRow").replaceChildren(...tiles.map(({ c, mons: ms }) => {
    const span = (cur.s.screens === "span" || c.key === "span") && mons.length > 1;
    // across all screens: the whole area they cover together; else that screen (or the main one)
    const box = span ? { width: Math.max(...mons.map((x) => x.x + x.width)) - Math.min(...mons.map((x) => x.x)),
                         height: Math.max(...mons.map((x) => x.y + x.height)) - Math.min(...mons.map((x) => x.y)) } : null;
    const m = box || ms.find(Boolean) || mons.find((x) => x.primary) || mons[0] || { width: 16, height: 9 };
    const w = m.width;
    const at = c.focus || CROP_AT[crop] || [0.5, 0.5];
    const where = span || ms.length > 1 ? "All screens" : screenName(m, mons);
    const btn = (cls, name, label, on, fn) => el("button", { type: "button", class: `thumb-btn${on ? " on" : ""}`,
      title: label, "aria-label": `${label}: ${c.title}`, "aria-pressed": String(!!on), onclick: fn }, icon(name));
    return el("figure", { class: `now-tile${c.name === cur.sel ? " sel" : ""}`, style: `flex:${w} 1 0` },
      el("div", { class: "now-pic", role: "button", tabindex: "0", title: "About this painting (shown on the right)",
        style: `aspect-ratio:${w}/${m.height}`, onclick: () => showAbout(c.name),
        onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showAbout(c.name); } } },
        el("img", { src: thumbUrl(c.name, true), alt: c.title,
          style: crop === "whole" ? "object-fit:contain" : `object-position:${at[0] * 100}% ${at[1] * 100}%` })),
      el("figcaption", {},
        el("div", { class: "t" }, el("b", {}, c.title),
          el("span", {}, [where, [c.maker, c.year].filter(Boolean).join(", ")].filter(Boolean).join(" · "))),
        el("span", { class: "thumbs" },
          btn("fav", "heart", c.favourite ? "Favourite (click to undo)" : "Favourite: comes up more often", c.favourite,
            () => api("/api/collection", { action: "favourite", name: c.name, on: !c.favourite })
              .then(() => api("/api/rotation")).then(setRotation).catch((e) => toast(e.message))),
          btn("up", "up", "More like this", c.thumb === 1,
            () => rotation("thumb", { name: c.name, value: c.thumb === 1 ? 0 : 1 })),
          btn("down", "down", "Less like this: it goes, and the Curator looks for fewer like it", c.thumb === -1,
            () => rotation("thumb", { name: c.name, value: -1 })),
          c.fromCurator ? el("button", { type: "button", class: "small keep-btn",
            title: "Chosen by the Curator. Keep it: it moves to My collection and stays.",
            onclick: () => api("/api/collection", { action: "keep", name: c.name })
              .then(() => { toast(`“${c.title}” is in My collection now.`); return loadItems(); })
              .then(() => api("/api/rotation")).then(setRotation)
              .then(() => { if (cur.sel === c.name) loadAbout(true); })
              .catch((e) => toast(e.message)) }, "Keep") : null)));
  }));
}

// About the chosen painting, beside the preview (instead of a separate page)
function showAbout(name, pinned = false) {
  cur.sel = name;
  cur.selPinned = pinned;                    // from Coming next / Recently chosen: not on screen
  for (const t of document.querySelectorAll("#nowRow .now-tile")) t.classList.remove("sel");
  renderOnScreens();
  loadAbout(true);
}

function loadAbout(force = false) {
  const box = $("nowAboutBox");
  if (!box || !cur.sel || (!force && box.dataset.name === cur.sel)) return;
  renderAbout(box, cur.sel, { compact: true, onChange: () => { box.dataset.name = ""; loadItems().then(loadAbout); } });
}

// Links to a painting's page in Coming next and Recently chosen: show it beside the preview
function aboutLinks(container) {
  container.addEventListener("click", (e) => {
    const a = e.target.closest('a[href^="painting.html"]');
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    showAbout(new URL(a.href).searchParams.get("name"), true);
    $("nowRow").closest("section").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

// Screens: the same choice as in Settings › Your screens
function renderScreensPick() {
  $("rowScreensCur").hidden = (cur.rot.screens || cur.options.screens || []).length < 2;
  for (const b of $("segScreensCur").querySelectorAll("button")) {
    const on = b.dataset.v === (cur.s.screens || "each");
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  }
}

function renderNow() {
  renderScreensPick();
  renderOnScreens();
  loadAbout();
  renderUpcoming();
  renderAskBtn();
  renderLearned();
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
  $("tasteBox").classList.toggle("dim", cur.s.mode !== "curator");
  $("tasteNote").textContent = cur.s.mode === "curator"
    ? "Tap what you'd like more of. Your thumbs up and down do the rest."
    : "Used when the Curator chooses: switch to “Curator chooses” in the bar at the bottom.";
}

// Subjects as chips: on = "More" (or "A lot"). Fine-tune has the sliders for every level.
function renderChips() {
  $("subjectChips").replaceChildren(...groupItems("subjects").map(([key, label]) => {
    const lv = level("subjects", key), on = lv >= 3;
    return el("button", {
      type: "button", class: `chip${on ? " on" : ""}${lv <= 1 ? " less" : ""}`, "aria-pressed": String(on),
      title: lv === 0 ? "Never: click to look for it again" : on ? "Click: back to normal" : "Click: more of this",
      onclick: () => {
        cur.s.curatorTaste = cur.s.curatorTaste || {};
        cur.s.curatorTaste.subjects = { ...(cur.s.curatorTaste.subjects || {}), [key]: on ? 2 : 3 };
        saveTaste();
        renderChips();
        if (cur.group === "subjects") renderSliders();
      } }, lv === 0 ? `${label} · never` : label);
  }));
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
  // saved, then "Coming next" is planned again with the new sliders
  tasteTimer = setTimeout(() => saveSettings({ curatorTaste: cur.s.curatorTaste })
    .then(() => api("/api/rotation")).then(setRotation).catch(() => {}), 400);
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
      if (group === "subjects") renderChips();
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

function renderLearned() {
  const L = cur.rot.learned || {};
  $("learnedBox").hidden = !(L.up || L.down);
  if (!(L.up || L.down)) return;
  $("learnedCount").textContent = [L.up ? `${L.up} × more like this` : "", L.down ? `${L.down} × less` : ""]
    .filter(Boolean).join(" · ");
  $("learned").replaceChildren(
    ...(L.more || []).map((x) => el("span", { class: "chip-more" }, `more ${x}`)),
    ...(L.less || []).map((x) => el("span", { class: "chip-less" }, `less ${x}`)),
    el("button", { type: "button", class: "link", title: "The Curator forgets your thumbs (paintings you took away stay away)",
      onclick: () => rotation("forgetThumbs") }, "Forget"));
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
  setCollectionCount(d.mine);
}

async function init() {
  mountShell("curator");
  const [s, rot, options, sources] = await Promise.all([
    api("/api/settings"), api("/api/rotation"), api("/api/options"), api("/api/sources")]);
  Object.assign(cur, { s, rot, options, sources });
  await loadItems();

  setIntervalUi(s.interval || 60);
  $("segScreensCur").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b || b.dataset.v === (cur.s.screens || "each")) return;
    cur.s.screens = b.dataset.v;
    renderScreensPick();
    await saveSettings({ screens: b.dataset.v });
    refreshLabel();                              // shows it on your screens right away
  });
  setupUpcoming();
  aboutLinks($("nextRow"));
  aboutLinks($("recent"));
  $("timeOfDay").checked = !!s.timeOfDay;
  $("seasons").checked = !!s.seasons;
  $("lockScreen").checked = !!s.lockScreen;
  $("curatorDaily").value = String([1, 2, 3, 5].includes(s.curatorDaily) ? s.curatorDaily : 3);
  $("curatorMax").value = String([10, 20, 30, 50, 100].includes(s.curatorMax) ? s.curatorMax : 20);
  $("surprise").value = String(Number.isInteger(s.curatorSurprise) ? s.curatorSurprise : 2);
  $("surpriseVal").textContent = SURPRISE[Number($("surprise").value)];
  renderNow();
  renderSource();
  renderSliders();
  renderChips();
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
  // "Coming next" is planned again for the new mood
  const moodSwitch = (key) => (e) => saveSettings({ [key]: e.target.checked })
    .then(() => api("/api/rotation")).then(setRotation).catch(() => {});
  $("timeOfDay").addEventListener("change", moodSwitch("timeOfDay"));
  $("seasons").addEventListener("change", moodSwitch("seasons"));
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
  $("curatorMax").addEventListener("change", () => saveSettings({ curatorMax: Number($("curatorMax").value) }));
  $("askBtn").addEventListener("click", async () => {
    asking = true;
    renderAskBtn();
    await rotation("curator", {}, (r) => ((r.curator || []).length ? ""
      : r.offline || r.curatorWaiting ? "You seem to be offline. Your paintings keep changing; the Curator looks for new ones once you're back online."
      : "The Curator found nothing new right now. Try again later or loosen your taste a little."));
    asking = false;
    renderAskBtn();
  });
}

init().catch((e) => toast(`Couldn't load the Curator: ${e.message}`));
