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
      wiki,
      el("dl", {}, ...facts.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))])),
      ...(d.credit ? [el("p", { class: "muted" }, d.credit)] : [])));

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
