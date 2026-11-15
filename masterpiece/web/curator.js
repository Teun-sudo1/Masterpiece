"use strict";
// The Curator tab: what's on your desktop, how it changes, and your taste.

const cur = { s: {}, rot: {}, options: {}, sources: [], items: [], group: "subjects" };
const PRESET_INTERVALS = [10, 30, 60, 180, 1440];
const LEVELS = ["Never", "Less", "Normal", "More", "A lot"];
const SURPRISE = ["Never", "Rarely", "Sometimes", "Often", "Very often"];
const thumbUrl = (name, large) => `/api/thumb?name=${encodeURIComponent(name)}${large ? "&size=large" : ""}`;

async function saveSettings(updates, msg) {
  try {
    cur.s = await api("/api/settings", updates);
    if (msg) toast(msg);
  } catch (e) { toast(`Couldn't save: ${e.message}`); }
}

// ------------------------------------------------------------------ now on your screens
function renderNow() {
  const r = cur.rot;
  const shown = r.shown || [];
  const items = Object.fromEntries(cur.items.map((i) => [i.name, i]));
  $("nowItems").replaceChildren(...(shown.length ? shown : [null]).map((c) => {
    if (!c) {
      return el("div", { class: "now-empty" },
        el("b", {}, r.count ? "Nothing from Masterpiece on your desktop yet." : "Your collection is still empty."),
        el("span", {}, r.count ? "Press Start to begin." : "Let the Curator choose, or add paintings from Search art."));
    }
    const it = items[c.name] || {};
    return el("a", { class: "now-item", href: `painting.html?name=${encodeURIComponent(c.name)}`, title: "About this painting" },
      el("img", { src: thumbUrl(c.name, true), alt: c.title }),
      el("div", { class: "now-text" },
        el("span", { class: "now-screen" }, c.screen),
        el("b", {}, c.title),
        el("span", {}, [c.maker || it.maker, it.year].filter(Boolean).join(", ")),
        it.curator ? el("span", { class: "now-reason" }, icon("sparkle"), it.curator) : null));
  }));

  const active = !!r.active, paused = !!r.paused;
  let status;
  if (!active) status = "Not running";
  else if (paused) status = "Paused";
  else status = `Changes ${intervalText(r.interval)}${r.nextRun ? ` · next at ${shortTime(r.nextRun)}` : ""}`;
  $("nowStatus").replaceChildren(el("span", { class: `dot${active && !paused ? " on" : ""}` }), status);
  $("startBtn").hidden = active;
  $("startBtn").textContent = cur.s.mode === "curator" && !r.count ? "Let the Curator start" : "Start";
  $("pauseBtn").hidden = !active;
  $("pauseBtn").replaceChildren(icon(paused ? "play" : "pause"));
  $("pauseBtn").title = paused ? "Resume" : "Pause";
  $("prevBtn").disabled = !r.hasPrevious;
  $("nextBtn").disabled = !r.count;
  $("restoreBtn").hidden = !(active || r.backup);
}

function shortTime(s) {
  const m = String(s).match(/(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?/i);
  if (!m) return s;
  let h = Number(m[1]);
  if (m[3]) h = (h % 12) + (/pm/i.test(m[3]) ? 12 : 0);
  return `${String(h).padStart(2, "0")}:${m[2]}`;
}

function intervalText(min) {
  min = Number(min) || 60;
  if (min % 1440 === 0) return min === 1440 ? "every day" : `every ${min / 1440} days`;
  if (min % 60 === 0) return min === 60 ? "every hour" : `every ${min / 60} hours`;
  return `every ${min} minutes`;
}

async function rotation(action, extra = {}, msg) {
  try {
    const r = await api("/api/rotation", { action, ...extra });
    cur.rot = r;
    if (r.curator && r.curator.length) await loadItems();
    renderNow();
    renderRecent();
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

async function refreshLabel(msg) {
  try {
    const r = await api("/api/rotation", { action: "refresh" });
    toast(Object.keys(r.wallpapers || {}).length ? "Label updated on your desktop." : msg || "Saved.");
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

  $("prevBtn").replaceChildren(icon("prev"));
  $("nextBtn").replaceChildren(icon("next"));
  setIntervalUi(s.interval || 60);
  $("screensRow").hidden = (options.screens || []).length < 2;
  $("screens").value = s.screens || "each";
  $("label").checked = !!s.label;
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
  $("nextBtn").addEventListener("click", () => rotation("next"));
  $("prevBtn").addEventListener("click", () => rotation("previous"));
  $("pauseBtn").addEventListener("click", () => rotation(cur.rot.paused ? "resume" : "pause", {},
    cur.rot.paused ? "The rotation continues." : "Paused: this painting stays until you resume."));
  $("startBtn").addEventListener("click", async () => {
    const b = $("startBtn");
    b.disabled = true;
    b.textContent = cur.s.mode === "curator" && !cur.rot.count ? "The Curator is choosing…" : "Starting…";
    await rotation("start", { interval: intervalMinutes() }, (r) => {
      const c = r.curator || [];
      return c.length ? `The Curator chose ${c.length} painting${c.length === 1 ? "" : "s"} for you. Running ${intervalText(r.interval)}.`
        : `Running ${intervalText(r.interval)}.`;
    });
    b.disabled = false;
  });
  $("restoreBtn").addEventListener("click", () => rotation("restore", {}, (r) =>
    r.restored === "previous" ? "Masterpiece stopped. Your previous wallpaper is back."
      : r.restored === "default" ? "Masterpiece stopped. Windows' default wallpaper is back." : "Masterpiece stopped."));

  $("sourcePick").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b || b.dataset.mode === cur.s.mode) return;
    cur.rot = await api("/api/rotation", { action: "source", mode: b.dataset.mode });
    cur.s.mode = cur.rot.mode;
    renderSource();
    renderNow();
    toast(cur.s.mode === "curator" ? "The Curator now adds new paintings for you every day."
      : "Only your own collection is shown now.");
  });
  const onInterval = () => {
    $("customWrap").hidden = $("interval").value !== "custom";
    rotation("interval", { interval: intervalMinutes() }, (r) => r.active ? `Now ${intervalText(r.interval)}.` : "Saved.");
  };
  $("interval").addEventListener("change", () => {
    if ($("interval").value === "custom") { $("customWrap").hidden = false; $("customN").focus(); return; }
    onInterval();
  });
  $("customN").addEventListener("change", onInterval);
  $("customUnit").addEventListener("change", onInterval);
  $("screens").addEventListener("change", async () => {
    await saveSettings({ screens: $("screens").value });
    refreshLabel("Saved. Used from the next painting on.");
  });
  $("label").addEventListener("change", async () => {
    await saveSettings({ label: $("label").checked });
    refreshLabel();
  });
  $("labelBtn").addEventListener("click", () => {
    const first = (cur.rot.shown || [])[0];
    const it = first ? cur.items.find((i) => i.name === first.name) : cur.items[0];
    openLabelDialog({
      screens: options.screens,
      sample: it ? { title: it.title, maker: it.maker, year: it.year, museum: it.museum, thumb: thumbUrl(it.name, true) } : null,
      pos: cur.s.labelPos, style: cur.s.labelStyle,
      onDone: async (pos, style) => {
        await saveSettings({ labelPos: pos, labelStyle: style });
        if ($("label").checked) refreshLabel();
      },
    });
  });
  $("timeOfDay").addEventListener("change", (e) => saveSettings({ timeOfDay: e.target.checked }, "Saved."));
  $("seasons").addEventListener("change", (e) => saveSettings({ seasons: e.target.checked },
    e.target.checked ? "Paintings that suit the season now come up more often." : "Saved."));
  $("lockScreen").addEventListener("change", async (e) => {
    e.target.disabled = true;
    try {
      await api("/api/system", { action: "lockScreen", on: e.target.checked });
      cur.s.lockScreen = e.target.checked;
      toast(e.target.checked ? "The painting is on your lock screen too (Win+L to see it)." : "Your own lock-screen picture is back.");
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
  $("curatorDaily").addEventListener("change", () => saveSettings({ curatorDaily: Number($("curatorDaily").value) }, "Saved."));
  $("askBtn").addEventListener("click", async () => {
    const b = $("askBtn");
    b.disabled = true;
    b.textContent = "The Curator is looking…";
    await rotation("curator", {}, (r) => {
      const c = r.curator || [];
      return c.length ? `The Curator found ${c.length}: ${c.map((a) => `“${a.title}” (${a.reason.toLowerCase()})`).join("; ")}.`
        : "The Curator found nothing new right now. Try again later or loosen your taste a little.";
    });
    b.disabled = false;
    b.textContent = "Ask the Curator now";
  });
  // keep "now on your screens" fresh while the page is open
  setInterval(() => api("/api/rotation").then((r) => { cur.rot = r; renderNow(); }).catch(() => {}), 60000);
}

init().catch((e) => toast(`Couldn't load the Curator: ${e.message}`));
