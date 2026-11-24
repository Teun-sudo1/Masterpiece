"use strict";
// The guided tour on Search art. Needs shell.js.
//   - first use: every step;
//   - after an update: only the steps that are new since the version you had ("since");
//   - Settings → "Take the tour" plays it all again.
// A step with only `news` (no `text`) is shown after an update only.

const TOUR_STEPS = [
  { sel: "#panel", since: "0.4.0", title: "Filters",
    text: "Narrow the search by museum, region, subject, period, colour and fit. The ‹ at the top hides the panel." },
  { sel: ".map-wrap", since: "0.4.1", title: "Click the world",
    text: "Choose one or more regions on the map; click again to remove one. Hover to see how many museums cover it.",
    news: "New: Latin America, Oceania, Africa and Russia, on a bigger map. Choose regions by clicking them." },
  { sel: ".card .pick", since: "0.3.0", title: "Pick paintings",
    text: "Click + on the paintings you like, then press Add to collection in the bar that appears. Click a painting itself for a large preview." },
  { sel: '[data-tab="collection"]', since: "0.4.0", title: "My collection",
    text: "Your paintings. Mark favourites (they come up more often), show one right now, or skip it." },
  { sel: '[data-tab="curator"]', since: "0.4.0", title: "The Curator",
    text: "What is on your screens now (with ♥ and thumbs up or down), what comes next, how often it changes, and what the Curator looks for when it finds new paintings for you every day." },
  { sel: "#rotMode", since: "0.4.1", title: "Who chooses",
    text: "Curator chooses: new paintings every day that suit your taste, together with your own. My collection: only what you added or kept yourself.",
    news: "New: switch between the Curator and your own collection from any tab." },
  { sel: "#rotBar .now-controls", since: "0.4.1", title: "Your desktop, from every tab",
    text: "Previous, pause, next, and Restore my wallpaper, which puts back exactly what you had before.",
    news: "New: previous, pause, next and Restore are now in this bar on every tab." },
  { sel: '[data-tab="settings"]', since: "0.4.1", title: "Settings",
    text: "Your screens: a live preview with the layout and the label. Also a dark or light look, how many paintings to keep, start with Windows, updates and storage.",
    news: "New: a light look. Settings → Appearance." },
  { sel: "#verBtn", since: "0.4.2", title: "Updates",
    text: "Your version. When an update is ready it shows here; afterwards this tour shows you just what's new. Settings → Take the tour plays it again.",
    news: "New: this tour. After every update it shows only what changed. Settings → Take the tour plays all of it again." },
  { sel: '[data-tab="curator"]', since: "0.4.3", title: "The label, where you want it",
    news: "New: show the label on all screens, only the main one, or only the left or right screen. Curator → Your desktop → Label." },
  { sel: '[data-tab="curator"]', since: "0.4.3", title: "Less sky, more painting",
    news: "New: when a painting is cut to fit your screen, choose which part to keep: the middle, the bottom or the top. Curator → Your desktop → Cut to fit." },
  { sel: '[data-tab="curator"]', since: "0.5.0", title: "Your desktop, live",
    news: "New on the Curator tab: a live preview of your screens. See what is cut off, slide to choose the part you see, or show the whole painting with blurred edges, a mat or a frame." },
  { sel: '[data-tab="curator"]', since: "0.5.0", title: "Coming next",
    news: "New: see which paintings come next, drag them into another order or skip one. A painting that would look blurry on your screen says so. And the label can now pick dark or light text by itself (Auto)." },
  { sel: '[data-tab="curator"]', since: "0.5.1", title: "A slider for the part you see",
    news: "New: on the Curator tab, the slider beside each painting chooses the part you see (top … bottom). And pictures that are still loading now show a soft moving sheen." },
  { sel: '[data-tab="curator"]', since: "0.6.0", title: "More or less like this",
    news: "New: thumbs up or down beside each painting on the Curator tab (and in the tray menu). The Curator learns from them: more of that artist, subject and period, or less. Thumbs down also takes the painting away." },
  { sel: '[data-tab="curator"]', since: "0.6.0", title: "Time of day and seasons",
    news: "“Match time of day” and “Follow the seasons” now also decide what is coming next. When the evening starts or the season turns, Masterpiece plans again." },
  { sel: '[data-tab="settings"]', since: "0.6.0", title: "Your screens moved",
    news: "The live preview with the layout and the label is now in Settings → Your screens, with all the same options. The Curator tab is simpler: what's on your screens, what comes next and what the Curator looks for." },
  { sel: '[data-tab="collection"]', since: "0.6.0", title: "The Curator's own collection",
    news: "What the Curator chooses no longer lands in My collection. It has its own place: My collection › From the Curator. Keep one (or ♥ it) and it's yours. “My collection” in the bar below now really shows only your own paintings." },
  { sel: '[data-tab="collection"]', since: "0.6.0", title: "Save, share and read more",
    news: "Open a painting for a few lines from Wikipedia about it and its artist. Save the picture, save it as a postcard with its label, or copy the postcard to paste into a chat. Also in the tray menu." },
  { sel: "#rotBar", since: "0.6.0", title: "Works offline",
    news: "Without internet, Masterpiece keeps changing between the paintings you already have and says “Offline” down here. The Curator looks for new ones once you're back online." },
];

const vtuple = (v) => String(v || "0").split(".").map((n) => parseInt(n, 10) || 0);
function newer(a, b) {                       // is version a newer than b?
  const x = vtuple(a), y = vtuple(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
}

const tour = { steps: [], i: 0, update: null, current: "" };

// Called from Search art once it is set up.
async function maybeStartTour(settings) {
  let replay = false;
  try { replay = sessionStorage.getItem("tour") === "all"; sessionStorage.removeItem("tour"); } catch { /* fine */ }
  let u;
  try { u = await api("/api/update"); } catch { return; }
  tour.current = u.current;
  const seen = settings.tourVersion || "";
  if (replay || !seen) {
    startTour(TOUR_STEPS.filter((s) => s.text), null);
  } else if (newer(u.current, seen)) {
    const steps = TOUR_STEPS.filter((s) => newer(s.since, seen));
    if (steps.length) {
      renderWhatsNew(null);                 // the tour replaces the "What's new" banner
      startTour(steps, u.current);
    } else {
      finishTour();                          // nothing to show for this update
    }
  }
}

function startTour(steps, update) {
  Object.assign(tour, { steps, i: 0, update });
  if (!$("tourPop")) {
    document.body.append(
      el("div", { class: "tour-block", id: "tourBlock" }),
      el("div", { class: "tour-hole", id: "tourHole" }),
      el("div", { class: "tour-pop", id: "tourPop", role: "dialog", "aria-modal": "true", "aria-labelledby": "tourTitle" }));
    addEventListener("resize", () => tour.steps.length && placeTour());
    document.addEventListener("keydown", (e) => {
      if (!tour.steps.length) return;
      if (e.key === "Escape") finishTour();
      else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); tourGo(1); }
      else if (e.key === "ArrowLeft") tourGo(-1);
    });
  }
  showTourStep();
}

function tourTarget() {
  const s = tour.steps[tour.i];
  const t = s && document.querySelector(s.sel);
  return t && t.getClientRects().length ? t : null;
}

async function showTourStep() {
  for (let n = 0; n < 30 && !tourTarget(); n++) await new Promise((r) => setTimeout(r, 100));  // e.g. results still loading
  if (!tourTarget()) {                       // not on screen (panel hidden, no results): skip it
    tour.steps.splice(tour.i, 1);
    if (tour.i >= tour.steps.length) return finishTour();
    return showTourStep();
  }
  const s = tour.steps[tour.i], last = tour.i === tour.steps.length - 1;
  tourTarget().scrollIntoView({ block: "nearest" });
  $("tourPop").replaceChildren(
    el("div", { class: "tour-kicker" }, tour.update ? `New in ${tour.update}` : "Welcome to Masterpiece",
      el("span", {}, `${tour.i + 1} / ${tour.steps.length}`)),
    el("h3", { id: "tourTitle" }, s.title),
    el("p", {}, tour.update && s.news ? s.news : s.text),
    el("div", { class: "tour-actions" },
      last ? el("span") : el("button", { type: "button", class: "link", onclick: finishTour }, "Skip"),
      el("span", {},
        tour.i ? el("button", { type: "button", class: "small", onclick: () => tourGo(-1) }, "Back") : null,
        el("button", { type: "button", class: "primary small", onclick: () => tourGo(1) }, last ? "Done" : "Next"))));
  placeTour();
  $("tourPop").querySelector(".primary").focus();
  followTarget();
}

// the page may still shift (results, scrollbar, the version text arriving): keep the spotlight on it
let lastRect = "";
function followTarget() {
  clearInterval(followTarget.timer);
  followTarget.timer = setInterval(() => {
    const t = tour.steps.length && tourTarget();
    const r = t && t.getBoundingClientRect();
    const key = r ? `${r.left}|${r.top}|${r.width}|${r.height}|${innerWidth}|${innerHeight}` : "";
    if (key && key !== lastRect) { lastRect = key; placeTour(); }
  }, 150);
}

function placeTour() {
  const t = tourTarget();
  if (!t) return;
  const r = t.getBoundingClientRect(), pad = 6;
  Object.assign($("tourHole").style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`,
    width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px` });
  const pop = $("tourPop"), pw = pop.offsetWidth, ph = pop.offsetHeight, gap = 14;
  // beside a tall target, else below it, else above it; always inside the window
  let x, y;
  if (r.height > innerHeight * 0.5 && r.right + gap + pw < innerWidth) { x = r.right + gap; y = r.top + 20; }
  else if (r.bottom + gap + ph < innerHeight) { x = r.left + r.width / 2 - pw / 2; y = r.bottom + gap; }
  else { x = r.left + r.width / 2 - pw / 2; y = r.top - gap - ph; }
  pop.style.left = `${Math.min(Math.max(x, 12), innerWidth - pw - 12)}px`;
  pop.style.top = `${Math.min(Math.max(y, 12), innerHeight - ph - 12)}px`;
}

function tourGo(d) {
  const i = tour.i + d;
  if (i < 0) return;
  if (i >= tour.steps.length) return finishTour();
  tour.i = i;
  document.body.classList.add("tour-moving");      // glide from one step to the next
  showTourStep();
}

function finishTour() {
  tour.steps = [];
  clearInterval(followTarget.timer);
  document.body.classList.remove("tour-moving");
  for (const id of ["tourBlock", "tourHole", "tourPop"]) $(id) && $(id).remove();
  if (tour.current) api("/api/settings", { tourVersion: tour.current }).catch(() => {});
  if (tour.update) api("/api/update", { action: "seenWhatsNew" }).catch(() => {});
}
