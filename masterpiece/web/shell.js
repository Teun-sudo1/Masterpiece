"use strict";
// Shared by every page: helpers, the top bar with the four tabs, and the update notices.

const $ = (id) => document.getElementById(id);
const img = (url) => `/api/img?u=${encodeURIComponent(url)}`;
const fmt = (w, h) => `${w}×${h}`;

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

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "style") n.style.cssText = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c != null && c !== false) n.append(c);
  return n;
}

const ICONS = {
  plus: "M12 5v14M5 12h14", check: "M5 12.5l4.5 4.5L19 7", x: "M6 6l12 12M18 6L6 18",
  prev: "M15 5l-7 7 7 7", next: "M9 5l7 7-7 7", pause: "M8 5v14M16 5v14", play: "M7 5l12 7-12 7z",
  restore: "M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4", heart: "M12 20.5s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.6a4.3 4.3 0 0 1 7.5 2.7c0 5.6-7.5 10.2-7.5 10.2z",
  filter: "M4 6h16M7 12h10M10 18h4", sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
  chevron: "M6 9l6 6 6-6",
  up: "M7 11v9H4v-9h3zm0 0l4-8c1.7 0 2.8 1.2 2.4 2.9L13 9h5.4c1.3 0 2.2 1.2 1.9 2.4l-1.6 6.4c-.3 1.3-1.4 2.2-2.7 2.2H7",
  down: "M17 13V4h3v9h-3zm0 0l-4 8c-1.7 0-2.8-1.2-2.4-2.9L11 15H5.6c-1.3 0-2.2-1.2-1.9-2.4l1.6-6.4C5.6 4.9 6.7 4 8 4h9", globe: "M3 12h18M12 3c2.8 2.6 4.2 5.6 4.2 9s-1.4 6.4-4.2 9c-2.8-2.6-4.2-5.6-4.2-9S9.2 5.6 12 3z",
};
function icon(name, extra = "") {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  if (extra) svg.setAttribute("class", extra);
  if (name === "globe") {
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", "12"); c.setAttribute("cy", "12"); c.setAttribute("r", "9");
    svg.append(c);
  }
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

let toastTimer;

// Pictures fade in once they are there (CSS shows a sheen until then). One that keeps failing
// says so calmly; pictures that retry by themselves (data-retry-able) only after their last try.
document.addEventListener("load", (e) => {
  if (e.target.tagName === "IMG") e.target.classList.add("loaded");
}, true);
document.addEventListener("error", (e) => {
  const im = e.target;
  if (im.tagName !== "IMG" || !im.getAttribute("src")) return;
  if (im.hasAttribute("data-retry-able") && Number(im.dataset.retry || 0) < 2) return;
  const box = im.closest(".thumb");
  if (box) box.classList.add("failed");
}, true);
function toast(msg, ms = 5000) {
  let t = $("toast");
  if (!t) document.body.append(t = el("div", { id: "toast", class: "toast", role: "status" }));
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

// ------------------------------------------------------------------ top bar
const TABS = [
  ["search", "Search art", "/"],
  ["collection", "My collection", "collection.html"],
  ["curator", "Curator", "curator.html"],
  ["settings", "Settings", "settings.html"],
];

function mountShell(active) {
  // The top bar is written in every page's HTML (so nothing moves while a page loads);
  // here it only gets wired up. Older pages without it get one built.
  let bar = document.querySelector(".appbar");
  if (!bar) {
    bar = el("header", { class: "appbar" },
      el("a", { class: "brand", href: "/" }, el("span", {}, "Masterpiece")),
      el("nav", { class: "tabs", "aria-label": "Sections" },
        ...TABS.map(([key, label, href]) => el("a", {
          href, class: `tab${key === active ? " on" : ""}`, "aria-current": key === active ? "page" : false,
          "data-tab": key }, label, key === "collection" ? el("span", { class: "tab-count", id: "collCount" }) : null))),
      el("button", { type: "button", class: "ver", id: "verBtn", title: "Check for updates" }));
    document.body.prepend(bar);
  }
  try { setCollectionCount(Number(sessionStorage.getItem("collCount")) || 0); } catch { /* fine */ }
  const banners = el("div", { class: "banners", id: "banners" },
    el("div", { id: "whatsNew", class: "banner whats-new", role: "status", hidden: true },
      el("div", {}, el("b", { id: "whatsNewTitle" }), el("div", { class: "notes", id: "whatsNewNotes" })),
      el("span", { class: "banner-actions" },
        el("button", { type: "button", class: "link", id: "whatsNewPage", hidden: true }, "Release page"),
        el("button", { type: "button", class: "primary small", id: "whatsNewOk" }, "Got it"))),
    el("div", { id: "updateBar", class: "banner", role: "status", hidden: true },
      el("span", { id: "updateText" }),
      el("span", { class: "banner-actions" },
        el("button", { type: "button", class: "primary small", id: "updateInstall" }, "Install now"),
        el("button", { type: "button", class: "link", id: "updateNotes" }, "What's new"),
        el("button", { type: "button", class: "link", id: "updateLater" }, "Later")),
      el("div", { class: "progress", id: "updateBarProgress", hidden: true }, el("span", { id: "updateProgress" }))));
  bar.after(banners);
  setupUpdates();
  setupRotBar();
  api("/api/settings").then((s) => applyTheme(s.theme)).catch(() => {});
  api("/api/saved").then((ids) => setCollectionCount(ids.length)).catch(() => {});
}

function setCollectionCount(n) {
  const c = $("collCount");
  if (c) c.textContent = n ? String(n) : "";
  try { sessionStorage.setItem("collCount", String(n || 0)); } catch { /* fine */ }
}

// ------------------------------------------------------------------ light / dark
const lightQuery = matchMedia("(prefers-color-scheme: light)");
let themeChoice = "dark";
function applyTheme(choice) {
  themeChoice = ["light", "system"].includes(choice) ? choice : "dark";
  const t = themeChoice === "system" ? (lightQuery.matches ? "light" : "dark") : themeChoice;
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("theme", themeChoice); } catch { /* fine */ }
}
lightQuery.addEventListener("change", () => applyTheme(themeChoice));

// ------------------------------------------------------------------ rotation bar (every page)
let rotState = null, rotBusy = false;

function intervalText(min) {
  min = Number(min) || 60;
  if (min % 1440 === 0) return min === 1440 ? "every day" : `every ${min / 1440} days`;
  if (min % 60 === 0) return min === 60 ? "every hour" : `every ${min / 60} hours`;
  return `every ${min} minutes`;
}

function shortTime(s) {
  const m = String(s).match(/(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?/i);
  if (!m) return s;
  let h = Number(m[1]);
  if (m[3]) h = (h % 12) + (/pm/i.test(m[3]) ? 12 : 0);
  return `${String(h).padStart(2, "0")}:${m[2]}`;
}

function renderRotBar(r) {
  if (!$("rotBar") || !r) return;
  const active = !!r.active, paused = !!r.paused;
  const status = !active ? (r.count ? "Not running" : "Your collection is still empty")
    : paused ? "Paused" : `Changes ${intervalText(r.interval)}${r.nextRun ? ` · next at ${shortTime(r.nextRun)}` : ""}`;
  $("rotStatus").replaceChildren(...[el("span", { class: `dot${active && !paused ? " on" : ""}` }), status,
    r.offline && el("span", { class: "offline-pill", title: "No internet connection. Masterpiece keeps changing between "
      + `the ${r.count || ""} paintings you have; the Curator looks for new ones once you're back online.` }, "Offline")].filter(Boolean));
  for (const b of $("rotMode").querySelectorAll("button")) {
    const on = b.dataset.mode === (r.mode === "curator" ? "curator" : "rotate");
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  }
  $("rotStart").hidden = active;
  $("rotStart").disabled = rotBusy;
  $("rotPause").hidden = !active;
  $("rotPause").replaceChildren(icon(paused ? "play" : "pause"));
  $("rotPause").title = paused ? "Resume" : "Pause";
  $("rotPrev").disabled = rotBusy || !r.hasPrevious;
  $("rotNext").disabled = rotBusy || !r.count;
  $("rotRestore").hidden = !(active || r.backup);
}

// every change to the rotation goes through here, so the bar and the page stay in step
function setRotation(r) {
  rotState = r;
  renderRotBar(r);
  try { sessionStorage.setItem("rotState", JSON.stringify(r)); } catch { /* fine */ }
  document.dispatchEvent(new CustomEvent("rotation", { detail: r }));
}

async function rotAction(action, extra = {}) {
  rotBusy = true;
  renderRotBar(rotState);
  try { const r = await api("/api/rotation", { action, ...extra }); rotBusy = false; setRotation(r); return r; }
  catch (e) { toast(e.message); }
  finally { rotBusy = false; renderRotBar(rotState); }
}

function setupRotBar() {
  if (!$("rotBar")) return;
  try { renderRotBar(JSON.parse(sessionStorage.getItem("rotState") || "null")); } catch { /* fine */ }
  $("rotPrev").addEventListener("click", () => rotAction("previous"));
  $("rotNext").addEventListener("click", () => rotAction("next"));
  $("rotPause").addEventListener("click", () => rotAction(rotState && rotState.paused ? "resume" : "pause"));
  $("rotStart").addEventListener("click", () => rotAction("start"));
  $("rotRestore").addEventListener("click", () => rotAction("restore"));
  $("rotMode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (b && !b.classList.contains("on")) rotAction("source", { mode: b.dataset.mode });
  });
  const poll = () => api("/api/rotation").then(setRotation).catch(() => {});
  poll();
  setInterval(poll, 60000);
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
  ver.textContent = u.available ? `Update ${u.latest}` : `v${u.current}`;
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
      if (u.available) renderUpdate({ ...u, skipped: "" });
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
      toast("OK. Install it later via the version at the top right, or the tray menu.");
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

// Collapsible side panel (Search art, My collection); remembered per page
function setupPanel(key) {
  const layout = $("layout"), btn = $("panelToggle"), open = $("panelOpen");
  const set = (collapsed) => {
    layout.classList.toggle("collapsed", collapsed);
    btn.setAttribute("aria-expanded", String(!collapsed));
    try { localStorage.setItem(`panel:${key}`, collapsed ? "1" : ""); } catch { /* fine */ }
  };
  let start = false;
  try { start = localStorage.getItem(`panel:${key}`) === "1"; } catch { /* fine */ }
  set(start);
  btn.addEventListener("click", () => set(true));
  open.addEventListener("click", () => set(false));
}
