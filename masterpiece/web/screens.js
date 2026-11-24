"use strict";
// Settings → Your screens: the live preview with the layout and label settings (desk.js).

const cur = { s: {}, rot: {}, options: {} };
const thumbUrl = (name, large) => `/api/thumb?name=${encodeURIComponent(name)}${large ? "&size=large" : ""}`;

async function saveSettings(updates) {
  try { cur.s = await api("/api/settings", updates); }
  catch (e) { toast(`Couldn't save: ${e.message}`); }
}

async function refreshLabel() {
  try {
    await api("/api/rotation", { action: "refresh" });
    setRotation(await api("/api/rotation"));
  } catch (e) { toast(e.message); }
}

async function rotation(action, extra = {}) {
  try { const r = await api("/api/rotation", { action, ...extra }); setRotation(r); return r; }
  catch (e) { toast(e.message); }
}

async function initScreens() {
  if (!$("deskStage")) return;
  const [s, rot, options] = await Promise.all([api("/api/settings"), api("/api/rotation"), api("/api/options")]);
  Object.assign(cur, { s, rot, options });
  setupDesk();
  renderDesk();
  document.addEventListener("rotation", (e) => { cur.rot = e.detail; renderDesk(); });
  addEventListener("resize", () => renderDesk());
  if (location.hash === "#screens") $("screens").scrollIntoView();
}
initScreens().catch((e) => toast(`Couldn't load your screens: ${e.message}`));
