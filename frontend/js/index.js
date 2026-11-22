import { api, el, fmtDateTime, health, imgUrl } from "./common.js";

const grid = document.getElementById("grid");
const summary = document.getElementById("summary");
let cams = [];

function card(id, c) {
  const h = health(c);
  const media = c.last_image
    ? el("img", { className: "thumb", src: imgUrl(c.last_image), alt: c.name, loading: "lazy" })
    : el("div", { className: "thumb" });
  return el("a", { className: "card", href: `camera.html?id=${encodeURIComponent(id)}` },
    media,
    el("div", { className: "body" },
      el("h2", { textContent: c.name }),
      el("div", { className: "muted", textContent: c.location || "" }),
      el("div", { className: "row" },
        el("span", { className: "muted", textContent: `Zadnji zajem: ${fmtDateTime(c.last_success_utc)}` }),
        el("span", { className: `badge ${h.key}`, textContent: h.label })),
      c.status === "error" && c.error
        ? el("div", { className: "muted", textContent: c.error, title: c.error }) : ""));
}

// Gorovje = zadnji del polja location ("Ime, Julijske Alpe").
const rangeOf = (c) => ((c.location || "").split(",").pop().trim()) || "Drugo";

function render() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const shown = cams.filter(([, c]) => `${c.name} ${c.location}`.toLowerCase().includes(q));
  const groups = new Map();
  for (const e of shown) {
    const r = rangeOf(e[1]);
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r).push(e);
  }
  const names = [...groups.keys()].sort((a, b) => a.localeCompare(b, "sl"));
  grid.replaceChildren(...names.flatMap((r) => [
    el("h2", { className: "range", id: "g-" + r, textContent: `${r} (${groups.get(r).length})` }),
    el("div", { className: "grid" }, ...groups.get(r).map(([id, c]) => card(id, c))),
  ]));
  const bad = cams.filter(([, c]) => health(c).key !== "ok").length;
  summary.textContent = `${cams.length} kamer, ${cams.length - bad} deluje` + (bad ? `, ${bad} s težavami` : "");
}

try {
  const status = await api("/api/status");
  cams = Object.entries(status.cameras || {}).filter(([, c]) => c.active !== false && c.status !== "inactive");
  cams.sort((a, b) => a[1].name.localeCompare(b[1].name, "sl"));
  render();
  if (status.updated_at) {
    document.getElementById("updated").textContent = `Status posodobljen: ${fmtDateTime(status.updated_at)}`;
  }
  if (!cams.length) summary.textContent = "Še ni nobenega zajema.";
} catch (e) {
  summary.replaceWith(el("div", { className: "error-box", textContent: `Napaka pri nalaganju: ${e.message}` }));
}
document.getElementById("search").addEventListener("input", render);
